"""
Sentry 错误监控集成（P2-#19）

安装
/root/deep-breath/backend/venv/bin/pip install sentry-sdk

在 main.py 最顶部加（Import 之前）::

    import sentry_sdk
    from app.core.config import settings

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,  # 从 .env 读取
        traces_sample_rate=0.1,    # 10% 性能追踪
        environment="production",
    )

在 .env 中加::

    SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx

在 app/core/config.py 的 Settings 类中加::

    SENTRY_DSN: str = ""
"""
