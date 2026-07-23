"""数据库引擎 & Session 管理"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

_url = settings.DATABASE_URL
_engine_kw = {"echo": settings.DEBUG}
if _url.startswith("postgresql"):
    _engine_kw["pool_size"] = 20
    _engine_kw["max_overflow"] = 40
    _engine_kw["pool_pre_ping"] = True
engine = create_async_engine(_url, **_engine_kw)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型继承此基类"""
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库 session"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """创建所有表（开发环境用，生产用 Alembic）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
