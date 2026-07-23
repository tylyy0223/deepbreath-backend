"""users 表增加 phone 列 + 全局唯一索引（幂等）

用法: cd /root/deep-breath/backend && venv/bin/python migrate_phone.py
"""
import asyncio

from sqlalchemy import text
from app.core.database import engine


async def main():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20)"))
        # partial unique index：允许多个 NULL（存量未绑定用户），非 NULL 全局唯一
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone_unique ON users(phone) WHERE phone IS NOT NULL"
        ))
    print("users.phone 列与唯一索引已就绪 ✅")


if __name__ == "__main__":
    asyncio.run(main())
