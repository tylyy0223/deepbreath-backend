"""
向后兼容的 config 模块
chatbot.py / rag_search.py 已不再依赖此文件（改用 app.services.env + os.environ）。
保留此文件供可能仍引用 `from config import ...` 的旧代码路径。
"""
import os

# 确保 .env 已加载
# （如果 env.py 先被导入则 no-op，否则触发手动加载）
try:
    from app.services.env import ensure_env  # noqa: F401
except ImportError:
    # 兜底：直接手动加载 .env（与 env.py 的 fallback 逻辑一致）
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.isfile(env_path):
        try:
            for line in open(env_path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip()
                    if k and k not in os.environ:
                        os.environ[k] = v.strip()
        except Exception:
            pass

# DeepSeek
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# HTTP 超时
HTTP_TIMEOUT_STREAM = 120
HTTP_TIMEOUT_ONCE = 60
HTTP_TIMEOUT_CONNECT = 10

# Wiki 数据库连接信息（供 psy_rag.py 等旧代码使用）
PSY_CHAT_DB = {
    "host": os.environ.get("WIKI_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("WIKI_DB_PORT", "5432")),
    "dbname": os.environ.get("WIKI_DB_NAME", "wikijs"),
    "user": os.environ.get("WIKI_DB_USER", "deepbreath_wiki_reader"),
    "password": os.environ.get("WIKI_DB_PASSWORD", ""),
}
