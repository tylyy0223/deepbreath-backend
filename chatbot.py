"""DeepSeek V4 对话 API 封装"""
import json, os, logging, traceback
import httpx

from app.services.env import ensure_env  # 统一 env 加载，消除 from config import 依赖

ensure_env()

logger = logging.getLogger("deepbreath.chatbot")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

HTTP_TIMEOUT_STREAM = 120
HTTP_TIMEOUT_ONCE = 60
HTTP_TIMEOUT_CONNECT = 10
MAX_RETRIES = 2

# 启动时显式检查 Key 是否可用
if not DEEPSEEK_API_KEY:
    logger.critical("DEEPSEEK_API_KEY is EMPTY! AI chat will fail. Check .env file.")
else:
    logger.info("DeepSeek API configured: base_url=%s, model=%s, key=%s...",
                DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_API_KEY[:8])


def _extract_error(resp) -> str:
    """从 DeepSeek 错误响应中提取可读的错误信息"""
    try:
        body = resp.json()
        err = body.get("error", {})
        msg = err.get("message", "") or json.dumps(body, ensure_ascii=False)
        return f"DeepSeek API {resp.status_code}: {msg}"
    except Exception:
        return f"DeepSeek API {resp.status_code}: {resp.text[:300]}"


async def chat_stream(messages, system_prompt=None, temperature=0.5):
    """
    流式调用 DeepSeek V4 API。
    yield {"type":"chunk","content":str} + 末尾 yield {"type":"usage","total_tokens":int}
    """
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs += messages if isinstance(messages, list) else [messages]

    total_tokens = 0  # ← 从 API 响应中捕获

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_STREAM) as client:
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with client.stream(
                    "POST", f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": msgs,
                        "temperature": temperature,
                        "stream": True,
                    },
                ) as resp:
                    if resp.status_code != 200:
                        err_msg = _extract_error(resp)
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
            except Exception:
                logger.error("[chat_stream] attempt %d/%d failed:\n%s",
                             attempt + 1, MAX_RETRIES + 1, traceback.format_exc())
                if attempt >= MAX_RETRIES:
                    raise


async def chat_once(messages, temperature=0.5):
    """非流式调用 DeepSeek V4 API，返回完整回复文本"""
    msgs = messages if isinstance(messages, list) else [messages]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_ONCE) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": msgs,
                "temperature": temperature,
                "stream": False,
            },
        )
        if resp.status_code != 200:
            err_msg = _extract_error(resp)
            logger.error("[chat_once] %s", err_msg)
            raise Exception(err_msg)
        return resp.json()["choices"][0]["message"]["content"]
