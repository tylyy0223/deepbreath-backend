"""
月度 Credits 赠送脚本（P1-#11b）
每月 1 日赠送给所有活跃用户 50 Credits

部署方式：crontab -e 添加：
  0 8 1 * * /root/deep-breath/backend/venv/bin/python /root/deep-breath/backend/monthly_gift.py >> /var/log/deepbreath-gift.log 2>&1
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import async_session
from app.services.credits_service import add_transaction

GIFT_AMOUNT = 50
GIFT_REF = "monthly-gift"


async def main():
    async with async_session() as db:
        # 查询活跃用户（30天内有登录记录）
        from sqlalchemy import select, text
        r = await db.execute(
            text("SELECT DISTINCT user_id, email FROM chat_sessions WHERE updated_at > NOW() - INTERVAL '30 days'")
        )
        users = r.fetchall()

        gifted = 0
        for user_id, email in users:
            try:
                await add_transaction(
                    db, user_id, GIFT_AMOUNT, "gift",
                    ref=GIFT_REF,
                    note=f"月度赠送 {GIFT_AMOUNT} Credits"
                )
                gifted += 1
                print(f"  OK  user_id={user_id}  email={email}")
            except Exception as e:
                print(f"  SKIP user_id={user_id}  {e}")

        await db.commit()
        print(f"Monthly gift done: {gifted} users received {GIFT_AMOUNT} Credits each")


if __name__ == "__main__":
    asyncio.run(main())
