"""
统一的 .env 加载模块
chatbot.py / rag_search.py / config.py 共用此模块，消除重复的 _load_env_fallback

加载顺序：
1. 如果 FastAPI app 已初始化 → app.core.config.settings 已自动加载 .env，无需操作
2. 如果作为独立模块被导入（先于 FastAPI 初始化）→ 手动解析 .env 文件注入 os.environ
"""
import os
import logging

logger = logging.getLogger("deepbreath.services.env")

_ENV_LOADED = False


def _find_env_path():
    """按优先级查找 .env 文件路径"""
    candidates = [
        # 部署路径（绝对路径作为兜底）
        "/root/deep-breath/backend/.env",
        # 相对于本文件：env.py → app/services/ → backend/
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def ensure_env():
    """确保环境变量已加载（幂等，仅首次调用时执行）"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    # 方式一：pydantic-settings 已自动加载（FastAPI 正常启动路径）
    try:
        from app.core.config import settings  # noqa: F401
        logger.debug("env loaded via pydantic-settings")
        return
    except Exception:
        pass

    # 方式二：手动解析 .env 文件（独立导入路径，如 preload 脚本）
    env_path = _find_env_path()
    if not env_path:
        logger.warning("no .env file found; relying on system environment variables")
        return

    try:
        loaded = 0
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k and k not in os.environ:
                    os.environ[k] = v.strip()
                    loaded += 1
        logger.info("env loaded from %s (%d vars)", env_path, loaded)
    except Exception as e:
        logger.warning("failed to load env from %s: %s", env_path, e)


# 模块导入时自动执行
ensure_env()
