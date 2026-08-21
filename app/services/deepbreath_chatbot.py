"""DeepSeek V4 对话 API 封装（原依赖 psy-chat config，已内迁到 DeepBreath）"""
import json, os, httpx, logging, traceback

logger = logging.getLogger("deepbreath.chatbot")


def _load_env_fallback():
    """兜底：从 .env 文件直接读取环境变量（防止 systemd EnvironmentFile 注入失败）"""
    env_file = "/root/deep-breath/backend/.env"
    if not os.path.exists(env_file):
        return
    try:
        for line in open(env_file, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                if k and k not in os.environ:
                    os.environ[k] = v.strip()
    except Exception:
        pass


_load_env_fallback()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# 启动时显式检查 Key 是否可用，记录到日志
if not DEEPSEEK_API_KEY:
    logger.critical("DEEPSEEK_API_KEY is EMPTY! AI chat will fail. Check .env file and systemd EnvironmentFile.")
else:
    logger.info(f"DeepSeek API configured: base_url={DEEPSEEK_BASE_URL}, model={DEEPSEEK_MODEL}, key={DEEPSEEK_API_KEY[:8]}...")
HTTP_TIMEOUT_STREAM = 120
HTTP_TIMEOUT_ONCE = 60
HTTP_TIMEOUT_CONNECT = 10
MAX_RETRIES = 2


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
    """流式调用 DeepSeek V4 API，yield 逐块文本"""
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs += messages if isinstance(messages, list) else [messages]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_STREAM) as client:
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with client.stream(
                    "POST", f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                    json={"model": DEEPSEEK_MODEL, "messages": msgs, "temperature": temperature, "stream": True},
                ) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        err_msg = _extract_error(resp)
                        logger.error(f"[chat_stream] {err_msg}")
                        raise Exception(err_msg)
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data.strip() == "[DONE]":
                                return
                            try:
                                delta = json.loads(data)["choices"][0]["delta"]
                                if "content" in delta and delta["content"]:
                                    yield delta["content"]
                            except (json.JSONDecodeError, KeyError, IndexError):
                                pass
                return
            except Exception:
                logger.error(f"[chat_stream] attempt {attempt+1}/{MAX_RETRIES+1} failed:\n{traceback.format_exc()}")
                if attempt >= MAX_RETRIES:
                    raise


async def chat_once(messages, temperature=0.5):
    """非流式调用 DeepSeek V4 API，返回完整回复文本"""
    msgs = messages if isinstance(messages, list) else [messages]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_ONCE) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": DEEPSEEK_MODEL, "messages": msgs, "temperature": temperature, "stream": False},
        )
        if resp.status_code != 200:
            err_msg = _extract_error(resp)
            logger.error(f"[chat_once] {err_msg}")
            raise Exception(err_msg)
        return resp.json()["choices"][0]["message"]["content"]
