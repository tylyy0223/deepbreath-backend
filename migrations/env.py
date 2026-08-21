"""
Alembic 迁移环境（异步 SQLAlchemy）
部署到 /root/deep-breath/backend/migrations/env.py
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# 复用 app 的配置（Pydantic Settings 自动从 .env 加载）
from app.core.config import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入所有模型以触发 __tablename__ 注册，取第一个 metadata 即可
from app.models.user import Base
from app.models.chat import Base as _
from app.models.diary import Base as _
from app.models.content import Base as _
from app.models.breath import Base as _
from app.models.cache import Base as _
from app.models.credits import Base as _

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
