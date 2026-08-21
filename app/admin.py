"""管理后台 API — 用户管理、数据统计"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from app.core.database import get_db
from app.core.security import get_current_user, require_role, Roles
from app.models.user import User

router = APIRouter(prefix="/api/v1/admin", tags=["管理后台"])


@router.get("/stats")
async def get_stats(
    current_user: dict = Depends(require_role(Roles.EDITOR)),
    db: AsyncSession = Depends(get_db),
):
    """获取仪表盘统计数据"""
    # 总用户
    r = await db.execute(select(func.count(User.id)))
    total_users = r.scalar() or 0

    # 今日活跃用户（最近24小时登录的）
    r2 = await db.execute(
        select(func.count(User.id)).where(
            User.updated_at >= text("now() - interval '24 hours'")
        )
    )
    active_today = r2.scalar() or 0

    return {
        "code": 0,
        "data": {
            "total_users": total_users,
            "active_today": active_today,
            "total_articles": 0,
            "total_posts": 0,
        },
    }


@router.get("/users")
async def list_users(
    current_user: dict = Depends(require_role(Roles.ADMIN)),
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
):
    """用户列表"""
    offset = (page - 1) * page_size
    r = await db.execute(
        select(User).order_by(User.id.desc()).offset(offset).limit(page_size)
    )
    users = r.scalars().all()

    r2 = await db.execute(select(func.count(User.id)))
    total = r2.scalar()

    return {
        "code": 0,
        "data": [
            {
                "id": u.id,
                "email": u.email,
                "nickname": u.nickname,
                "role": u.role,
                "status": u.status,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    role: str,
    current_user: dict = Depends(require_role(Roles.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """修改用户角色"""
    if role not in [Roles.USER, Roles.EDITOR, Roles.MODERATOR, Roles.ADMIN]:
        raise HTTPException(status_code=400, detail="无效角色")
    r = await db.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.role = role
    await db.flush()
    return {"code": 0, "message": f"用户角色已更新为 {role}"}


@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: int,
    status: str,
    current_user: dict = Depends(require_role(Roles.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """修改用户状态 (active/banned/deleted)"""
    if status not in ["active", "banned", "deleted"]:
        raise HTTPException(status_code=400, detail="无效状态")
    r = await db.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.status = status
    await db.flush()
    return {"code": 0, "message": f"用户状态已更新为 {status}"}


@router.get("/login-logs")
async def get_login_logs(
    page: int = 1,
    page_size: int = 30,
    user_id: int | None = None,
    action: str | None = None,
    current_user: dict = Depends(require_role(Roles.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """查看用户登录日志"""
    from app.models.cache import LoginLog
    q = select(LoginLog)
    if user_id:
        q = q.where(LoginLog.user_id == user_id)
    if action:
        q = q.where(LoginLog.action == action)
    q = q.order_by(LoginLog.created_at.desc())
    # count
    r = await db.execute(select(func.count()).select_from(q.subquery()))
    total = r.scalar() or 0
    # page
    q = q.offset((page - 1) * page_size).limit(page_size)
    r = await db.execute(q)
    logs = r.scalars().all()
    return {
        "code": 0,
        "data": [{
            "id": l.id, "user_id": l.user_id, "email": l.email,
            "action": l.action, "success": l.success,
            "ip_address": l.ip_address, "user_agent": l.user_agent[:200] if l.user_agent else "",
            "detail": l.detail,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        } for l in logs],
        "total": total, "page": page, "page_size": page_size,
    }
