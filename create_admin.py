"""创建系统管理员账号（幂等：已存在则仅提升角色，不改密码）

用法: cd /root/deep-breath/backend && venv/bin/python create_admin.py
"""
import asyncio
import secrets

from app.core.database import async_session
from app.core.security import hash_password
from app.models.user import User
from sqlalchemy import select

ADMIN_EMAIL = "admin@luoyuyu.cn"


async def main():
    async with async_session() as db:
        r = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        user = r.scalar_one_or_none()
        if user:
            if user.role != "admin":
                user.role = "admin"
                user.status = "active"
                await db.commit()
                print(f"已将现有账号 {ADMIN_EMAIL} 提升为 admin（密码未变）")
            else:
                print(f"管理员账号 {ADMIN_EMAIL} 已存在，无需操作")
            return

        password = secrets.token_urlsafe(12)
        db.add(User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(password),
            nickname="系统管理员",
            role="admin",
            status="active",
        ))
        await db.commit()
        print("管理员账号创建成功 ✅")
        print(f"  邮箱: {ADMIN_EMAIL}")
        print(f"  初始密码: {password}")
        print("  ⚠️ 请立即妥善保存，此密码只显示这一次")


if __name__ == "__main__":
    asyncio.run(main())
