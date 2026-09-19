"""应用配置 — 基于 Pydantic Settings，从环境变量 /.env 加载"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "深呼吸 DeepBreath"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # 数据库
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_USER: str = "deepbreath"
    DB_PASSWORD: str = ""
    DB_NAME: str = "deepbreath"

    @property
    def DATABASE_URL(self) -> str:
        import os
        direct = os.environ.get("DATABASE_URL")
        if direct:
            return direct
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # Redis
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    @property
    def REDIS_URL(self) -> str:
        pw = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{pw}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # JWT
    # JWT_SECRET_KEY 必填: 从 .env 读取, 不设默认值 (避免 .env 加载失败时用公开密钥伪造 token)
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 小时
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # AI
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    AI_DAILY_LIMIT_PER_USER: int = 50

    # 文件上传
    UPLOAD_DIR: str = "/data/deepbreath/uploads"
    MAX_UPLOAD_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: list[str] = ["jpg", "jpeg", "png", "gif", "webp", "mp3", "mp4"]

    # MiniMax TTS
    MINIMAX_API_KEY: str = ""

    # === 腾讯云短信 ===
    TENCENT_SMS_SDKAPPID: str = ""
    TENCENT_SMS_APPKEY: str = ""
    TENCENT_SMS_SIGN: str = ""
    TENCENT_SMS_TPL_ID: str = ""
    TENCENT_SMS_TPL_PARAMS: str = "{code}"

    # 邮件
    # === Wiki.js 数据库（参考文献 API）===
    WIKI_DB_HOST: str = "127.0.0.1"
    WIKI_DB_PORT: int = 5432
    WIKI_DB_NAME: str = "wikijs"
    WIKI_DB_USER: str = "postgres"
    WIKI_DB_PASSWORD: str = ""
    QQMAIL_PASSWORD: str = ""
    SMTP_HOST: str = "smtp.qq.com"
    SMTP_PORT: int = 465
    SMTP_USER: str = "505055601@qq.com"
    SMTP_PASSWORD: str = ""

    # 跨域 (main.py 里按环境拆分白名单; 此处默认仅 dev 本地, 生产必须 .env 显式覆盖)
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # 日志
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

# === 启动期安全校验: 防止 .env 加载失败导致 JWT 用公开默认值 ===
import sys as _sys
_jwt = settings.JWT_SECRET_KEY or ''
_errs = []
if not _jwt or len(_jwt) < 32:
    _errs.append('JWT_SECRET_KEY 未配置或太短 (当前 %d 字符, 要求 >= 32)' % len(_jwt))
if settings.CORS_ORIGINS == ["*"]:
    _errs.append("CORS_ORIGINS 仍为 '*', 与 allow_credentials=True 一起等于 CSRF 公开. 请显式设置白名单")
if _errs:
    print('\n[CONFIG ERROR] 启动被安全检查拦截:', file=_sys.stderr)
    for _e in _errs:
        print('  - ' + _e, file=_sys.stderr)
    _sys.exit(1)
