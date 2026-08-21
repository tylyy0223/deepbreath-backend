import asyncio
from app.core.database import engine, Base
from app.models.cache import TtsBinding
async def m():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("tts_bindings ready")
asyncio.run(m())
