"""
DeepBreath 测试配置 & Fixtures
使用 SQLite 内存数据库替代 PostgreSQL，Mock 外部依赖
"""
import sys
import os
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# 确保项目在 path 上
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ========== Mock 外部依赖（在导入 app 前执行）==========

# 先 mock app.core.config.settings，避免加载真实 .env 和 PostgreSQL 连接串
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-12345678"
os.environ["DEEPSEEK_API_KEY"] = "sk-test-mock-key"
os.environ["WIKI_DB_PASSWORD"] = ""
os.environ["DB_PASSWORD"] = ""

# Mock Redis（测试环境无 Redis）
mock_redis = AsyncMock()
mock_redis.ping = AsyncMock(return_value=True)
mock_redis.get = AsyncMock(return_value=None)
mock_redis.set = AsyncMock(return_value=True)
mock_redis.delete = AsyncMock(return_value=True)
mock_redis.exists = AsyncMock(return_value=False)
sys.modules["app.core.redis"] = MagicMock()
sys.modules["app.core.redis"].redis_client = mock_redis
sys.modules["app.core.redis"].store_refresh_token = AsyncMock(return_value=True)
sys.modules["app.core.redis"].validate_refresh_token = AsyncMock(return_value=True)
sys.modules["app.core.redis"].revoke_refresh_token = AsyncMock(return_value=True)

# Mock chatbot 模块——在 app 导入之前占位，避免 import 时报错
# 不 mock 全局 httpx（否则 ASGITransport 报废）


async def _mock_chat_stream(messages, system_prompt=None, temperature=0.5):
    yield {"type": "chunk", "content": "你好，这是测试回复。"}
    yield {"type": "usage", "total_tokens": 10}


async def _mock_chat_once(messages, temperature=0.5):
    return "你好，这是测试回复。"


_mock_chatbot_module = MagicMock()
_mock_chatbot_module.chat_stream = _mock_chat_stream
_mock_chatbot_module.chat_once = _mock_chat_once
_mock_chatbot_module.DEEPSEEK_API_KEY = "sk-test"
_mock_chatbot_module.DEEPSEEK_BASE_URL = "https://test"
_mock_chatbot_module.DEEPSEEK_MODEL = "test-model"
sys.modules["app.services.chatbot"] = _mock_chatbot_module

# Mock rag_search 模块
_mock_rag = MagicMock()
_mock_rag.search_wiki = lambda query, limit=5: {"results": [], "total": 0}
sys.modules["app.services.rag_search"] = _mock_rag

# Mock env 模块（chatbot.py 和 rag_search.py 导入它）
_mock_env = MagicMock()
_mock_env.ensure_env = lambda: None
sys.modules["app.services.env"] = _mock_env

# Mock psycopg2（Wiki RAG）
sys.modules["psycopg2"] = MagicMock()
sys.modules["psycopg2.extras"] = MagicMock()

# Mock app.services.sms_service
mock_sms = MagicMock()
mock_sms.valid_phone.return_value = True
mock_sms.mask_phone = lambda p: f"{p[:3]}****{p[-4:]}" if p and len(p) >= 11 else p or ""
mock_sms.send_code = AsyncMock(return_value=True)
mock_sms.verify_code = AsyncMock(return_value=True)  # 测试环境始终放行
sys.modules["app.services.sms_service"] = mock_sms

# ========== 测试引擎 & 会话 ==========


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    from app.models.user import Base as UserBase
    from app.models.content import Base as ContentBase
    from app.models.chat import Base as ChatBase
    from app.models.diary import Base as DiaryBase
    from app.models.cache import Base as CacheBase
    from app.models.credits import Base as CreditsBase

    async with test_engine.begin() as conn:
        for base in [UserBase, ContentBase, ChatBase, DiaryBase, CacheBase, CreditsBase]:
            await conn.run_sync(base.metadata.create_all)

    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        for base in [UserBase, ContentBase, ChatBase, DiaryBase, CacheBase, CreditsBase]:
            await conn.run_sync(base.metadata.drop_all)


@pytest.fixture
async def client(db_session):
    """FastAPI TestClient（异步）"""
    from httpx import AsyncClient, ASGITransport
    from app.core.database import get_db

    # 必须先导入 app，此时 mock 已生效
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
