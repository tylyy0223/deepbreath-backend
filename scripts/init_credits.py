"""Credits 初始化 — 建表 + 为存量用户补发注册赠送（幂等）

用法: cd /root/deep-breath/backend && venv/bin/python init_credits.py
"""
import asyncio

from app.core.database import engine, async_session, Base
from app.models.credits import CreditTransaction, CreditOrder, RedeemCode  # noqa: F401 注册到 metadata
from app.models.user import User
from app.services.credits_service import REGISTER_GIFT, add_transaction
from sqlalchemy import select


async def main():
    # 1. 建表（create_all 只创建缺失的表，不动已有表）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("表结构已就绪 ✅")

    # 2. 存量用户补发（没有 gift 流水的用户）
    async with async_session() as db:
        users = (await db.execute(select(User))).scalars().all()
        granted = 0
        for u in users:
            r = await db.execute(select(CreditTransaction).where(
                CreditTransaction.user_id == u.id, CreditTransaction.type == "gift"))
            if r.scalars().first():
                continue
            await add_transaction(db, u.id, REGISTER_GIFT, "gift", ref="backfill", note="存量用户补发注册赠送")
            granted += 1
            print(f"  补发 {u.email} +{REGISTER_GIFT}")
        await db.commit()
        print(f"补发完成：{granted}/{len(users)} 名用户 ✅")


if __name__ == "__main__":
    asyncio.run(main())
