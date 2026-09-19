"""DeepSeek V4 对话 API 封装（httpx 连接池复用 + 并发控制 + prompt cache）"""
import json, os, logging, traceback
import asyncio
import httpx

from app.services.env import ensure_env  # 统一 env 加载，消除 from config import 依赖

ensure_env()


def _load_env_fallback():
    """兜底：pydantic-settings 把 .env 加载到 settings 对象但不写回 os.environ，
    而本模块用 os.environ.get(...) 读 key → 必须显式 setdefault 到 os.environ 才能用。
    仅当关键 key（DEEPSEEK_API_KEY）不在 os.environ 时执行。
    """
    import os as _os
    if _os.environ.get("DEEPSEEK_API_KEY"):
        return  # 已经在 env 里（用户 set -a; source .env 启动），无需重复加载
    env_path = "/root/deep-breath/backend/.env"
    if not _os.path.isfile(env_path):
        return
    loaded = 0
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in _os.environ:
                _os.environ[k] = v.strip()
                loaded += 1
    if loaded:
        print(f"[chatbot env-fallback] loaded {loaded} vars from {env_path}")


_load_env_fallback()

logger = logging.getLogger("deepbreath.chatbot")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

HTTP_TIMEOUT_STREAM = 120
HTTP_TIMEOUT_ONCE = 60
HTTP_TIMEOUT_CONNECT = 10
MAX_RETRIES = 2

# === 全局并发信号量：防止多用户并发打爆 DeepSeek 配额（429）===
# 阈值可通过 DEEPSEEK_MAX_CONCURRENT 环境变量调整；uvicorn --workers 2 → 实际并发 = 2 * N
DEEPSEEK_MAX_CONCURRENT = int(os.environ.get("DEEPSEEK_MAX_CONCURRENT", "30"))
_deepseek_sem = asyncio.Semaphore(DEEPSEEK_MAX_CONCURRENT)

# === httpx 连接池：模块级单例，复用 TCP+TLS 握手，避免每次重建连接 ===
# - max_connections: 单 process 允许的总连接数（含 in-flight + keepalive）
# - max_keepalive_connections: 空闲连接池大小（避免每次都重建）
# - keepalive_expiry: 空闲连接多久后关闭（秒）
# - http2: DeepSeek 支持 HTTP/2，多路复用减少握手
_client_limits = httpx.Limits(
    max_connections=int(os.environ.get("DEEPSEEK_MAX_CONNECTIONS", "100")),
    max_keepalive_connections=int(os.environ.get("DEEPSEEK_MAX_KEEPALIVE", "20")),
    keepalive_expiry=30,
)
_client: httpx.AsyncClient | None = None


def _get_client(stream: bool = True) -> httpx.AsyncClient:
    """获取（或重建）共享 httpx.AsyncClient 单例
    
    stream=True  → 用流式超时（120s）
    stream=False → 用非流式超时（60s）
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                HTTP_TIMEOUT_STREAM if stream else HTTP_TIMEOUT_ONCE,
                connect=HTTP_TIMEOUT_CONNECT,
            ),
            limits=_client_limits,
            http2=True,
        )
    return _client


async def _close_client() -> None:
    """应用关闭时清理 httpx 连接池（lifespan 用）"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


# 启动时显式检查 Key 是否可用
if not DEEPSEEK_API_KEY:
    logger.critical("DEEPSEEK_API_KEY is EMPTY! AI chat will fail. Check .env file.")
else:
    logger.info(
        "DeepSeek API configured: base_url=%s, model=%s, key=%s... | "
        "sem=%d, conn=%d, keepalive=%d, http2=on",
        DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_API_KEY[:8],
        DEEPSEEK_MAX_CONCURRENT,
        _client_limits.max_connections,
        _client_limits.max_keepalive_connections,
    )


def _extract_error(resp) -> str:
    """从 DeepSeek 错误响应中提取可读的错误信息"""
    try:
        body = resp.json()
        err = body.get("error", {})
        msg = err.get("message", "") or json.dumps(body, ensure_ascii=False)
        return f"DeepSeek API {resp.status_code}: {msg}"
    except Exception:
        return f"DeepSeek API {resp.status_code}: {resp.text[:300]}"


async def _record_429(resp) -> None:
    """DeepSeek 429 限流：写日志 + Redis 计数器（管理后台并发监控可读）"""
    try:
        from app.core.redis import redis_client
        await redis_client.incr("stats:deepseek:429")
    except Exception:
        pass
    logger.error("[deepseek] 429 限流触发: %s", _extract_error(resp))


def _is_retryable(exc: Exception, attempt: int) -> bool:
    """判断异常是否值得重试（含指数退避）"""
    if attempt >= MAX_RETRIES:
        return False
    msg = str(exc).lower()
    # 429 / 5xx / 网络层错误（连接重置、TLS 握手失败）都重试
    if "429" in msg or "rate" in msg or "timeout" in msg or "connection" in msg:
        return True
    return False


def _backoff_delay(attempt: int) -> float:
    """指数退避：1s, 2s, 4s ... + 随机抖动（避免雪崩）"""
    import random
    return (2 ** attempt) + random.uniform(0, 0.5)


async def chat_stream(messages, system_prompt=None, temperature=0.5, prompt_cache_key: str | None = None):
    """
    流式调用 DeepSeek V4 API。
    
    prompt_cache_key: DeepSeek V4 服务端 prompt cache 键；相同 key 命中可省首字节 200-800ms。
                      推荐传 f"{model}:{mode}" 让同模式共享 system prompt cache。
    
    yield {"type":"chunk","content":str} + 末尾 yield {"type":"usage","total_tokens":int}
    """
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs += messages if isinstance(messages, list) else [messages]

    total_tokens = 0
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": msgs,
        "temperature": temperature,
        "stream": True,
    }
    if prompt_cache_key:
        payload["prompt_cache_key"] = prompt_cache_key

    client = _get_client(stream=True)
    async with _deepseek_sem:
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with client.stream(
                    "POST", f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        if resp.status_code == 429:
                            await _record_429(resp)
                        err_msg = _extract_error(resp)
                        # 429 / 5xx → 重试；4xx → 不重试
                        if resp.status_code == 429 or resp.status_code >= 500:
                            if attempt < MAX_RETRIES:
                                delay = _backoff_delay(attempt)
                                logger.warning(
                                    "[chat_stream] %s, retrying in %.1fs (attempt %d/%d)",
                                    err_msg, delay, attempt + 1, MAX_RETRIES,
                                )
                                await asyncio.sleep(delay)
                                continue
                        logger.error("[chat_stream] %s", err_msg)
                        raise Exception(err_msg)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            # 文本内容
                            delta = obj.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield {"type": "chunk", "content": content}
                            # Usage（出现在最后一个 chunk 中）
                            usage = obj.get("usage")
                            if usage:
                                total_tokens = usage.get("total_tokens", 0)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
                yield {"type": "usage", "total_tokens": total_tokens}
                return
            except Exception as exc:
                if _is_retryable(exc, attempt):
                    delay = _backoff_delay(attempt)
                    logger.warning(
                        "[chat_stream] attempt %d/%d failed, retrying in %.1fs: %s",
                        attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "[chat_stream] attempt %d/%d failed (no retry):\n%s",
                    attempt + 1, MAX_RETRIES + 1, traceback.format_exc(),
                )
                raise


async def chat_once(messages, temperature=0.5, prompt_cache_key: str | None = None):
    """非流式调用 DeepSeek V4 API，返回完整回复文本
    
    prompt_cache_key: 同 chat_stream
    """
    msgs = messages if isinstance(messages, list) else [messages]
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": msgs,
        "temperature": temperature,
        "stream": False,
    }
    if prompt_cache_key:
        payload["prompt_cache_key"] = prompt_cache_key

    client = _get_client(stream=False)
    async with _deepseek_sem:
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await client.post(
                    f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code != 200:
                    if resp.status_code == 429:
                        await _record_429(resp)
                    err_msg = _extract_error(resp)
                    if (resp.status_code == 429 or resp.status_code >= 500) and attempt < MAX_RETRIES:
                        delay = _backoff_delay(attempt)
                        logger.warning(
                            "[chat_once] %s, retrying in %.1fs (attempt %d/%d)",
                            err_msg, delay, attempt + 1, MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error("[chat_once] %s", err_msg)
                    raise Exception(err_msg)
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as exc:
                if _is_retryable(exc, attempt):
                    delay = _backoff_delay(attempt)
                    logger.warning(
                        "[chat_once] attempt %d/%d failed, retrying in %.1fs: %s",
                        attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "[chat_once] attempt %d/%d failed (no retry):\n%s",
                    attempt + 1, MAX_RETRIES + 1, traceback.format_exc(),
                )
                raise
