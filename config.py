"""DeepBreath 服务层配置 — 从环境变量读取（替代 psy-chat 的 config.py）"""
import os

def _env(key, fallback=""):
    return os.environ.get(key, fallback)

# DeepSeek
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY") or _env("DASHSCOPE_API_KEY")
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = "deepseek-v4-flash"
HTTP_TIMEOUT_STREAM = 120
HTTP_TIMEOUT_ONCE = 120
HTTP_TIMEOUT_CONNECT = 15.0

# Wiki.js（供 rag_search 用）
PSY_CHAT_DB = {
    "host": _env("WIKI_DB_HOST", "127.0.0.1"),
    "port": int(_env("WIKI_DB_PORT", "5432")),
    "dbname": _env("WIKI_DB_NAME", "wikijs"),
    "user": _env("WIKI_DB_USER", "deepbreath_wiki_reader"),
    "password": _env("WIKI_DB_PASSWORD", ""),
}
