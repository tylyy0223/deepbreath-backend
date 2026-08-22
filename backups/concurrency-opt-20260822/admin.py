"""管理后台 API — 用户管理、数据统计"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime, timezone, timedelta
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


@router.get("/ai-usage")
async def ai_usage(
    days: int = 30,
    current_user: dict = Depends(require_role(Roles.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """AI Token 用量统计 + 成本估算（DeepSeek V4: 输入 ¥1/1M tokens, 输出 ¥2/1M tokens）"""
    from app.models.chat import ChatMessage, ChatSession

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 总 AI 消息数
    r = await db.execute(
        select(func.count(ChatMessage.id))
        .where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
    )
    total_ai_msgs = r.scalar() or 0

    # 总 Token 估算（中文：~2 字符/token，英文：~4 字符/token，取平均 ~3）
    r = await db.execute(
        select(func.sum(func.length(ChatMessage.content)))
        .where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
    )
    total_chars = r.scalar() or 0
    total_output_tokens = total_chars // 3

    r = await db.execute(
        select(func.sum(func.length(ChatMessage.content)))
        .where(ChatMessage.role == "user", ChatMessage.created_at >= since)
    )
    total_input_chars = r.scalar() or 0
    total_input_tokens = total_input_chars // 3

    # 系统提示词 token 估算（每次对话约 200-500 tokens，取 300）
    system_tokens = total_ai_msgs * 300

    # 成本（DeepSeek V4 标准价）
    input_cost = (total_input_tokens + system_tokens) / 1_000_000 * 1.0
    output_cost = total_output_tokens / 1_000_000 * 2.0

    # 每日统计
    r = await db.execute(
        select(
            func.date(ChatMessage.created_at).label("d"),
            func.count(ChatMessage.id).label("cnt"),
            func.sum(func.length(ChatMessage.content)).label("chars"),
        )
        .where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
        .group_by(text("d")).order_by(text("d"))
    )
    daily = [{"date": str(row.d), "messages": row.cnt, "chars": row.chars or 0, "tokens": (row.chars or 0) // 3} for row in r.all()]

    # 按用户统计
    r = await db.execute(
        select(
            ChatSession.user_id,
            func.count(ChatMessage.id).label("cnt"),
            func.sum(func.length(ChatMessage.content)).label("chars"),
        )
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
        .group_by(ChatSession.user_id)
        .order_by(text("chars DESC"))
        .limit(20)
    )
    per_user = [{"user_id": row.user_id, "messages": row.cnt, "chars": row.chars or 0, "tokens": (row.chars or 0) // 3} for row in r.all()]

    return {
        "code": 0,
        "data": {
            "period_days": days,
            "total_ai_messages": total_ai_msgs,
            "estimated_input_tokens": total_input_tokens + system_tokens,
            "estimated_output_tokens": total_output_tokens,
            "estimated_cost_cny": round(input_cost + output_cost, 2),
            "daily": daily,
            "top_users": per_user,
        },
    }


@router.get("/analytics")
async def analytics(
    days: int = 30,
    current_user: dict = Depends(require_role(Roles.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """全站统计分析 — 总量、每日趋势、情绪分布、模块使用分布"""
    from app.models.chat import ChatSession, ChatMessage
    from app.models.diary import MoodEntry
    from app.models.breath import BreathSession, BreathExercise
    from app.models.community import CommunityPost
    from app.models.content import Article

    since = datetime.now(timezone.utc) - timedelta(days=days)

    async def _count(model, *where):
        r = await db.execute(select(func.count(model.id)).where(*where) if where else select(func.count(model.id)))
        return int(r.scalar() or 0)

    # ---- 总量 ----
    r = await db.execute(select(func.coalesce(func.sum(Article.view_count), 0)))
    article_views = int(r.scalar() or 0)
    totals = {
        "users": await _count(User),
        "chat_sessions": await _count(ChatSession),
        "ai_messages": await _count(ChatMessage, ChatMessage.role == "assistant"),
        "diary_entries": await _count(MoodEntry),
        "breath_sessions": await _count(BreathSession, BreathSession.completed == True),  # noqa: E712
        "community_posts": await _count(CommunityPost, CommunityPost.status == "active"),
        "articles": await _count(Article, Article.status == "published"),
        "article_views": article_views,
    }

    # ---- 每日趋势 ----
    async def _daily(model, date_col, *where):
        q = (
            select(func.date(date_col).label("d"), func.count(model.id).label("cnt"))
            .where(date_col >= since, *where)
            .group_by(text("d")).order_by(text("d"))
        )
        r = await db.execute(q)
        return [{"date": str(row.d), "count": row.cnt} for row in r.all()]

    daily = {
        "new_users": await _daily(User, User.created_at),
        "ai_messages": await _daily(ChatMessage, ChatMessage.created_at, ChatMessage.role == "assistant"),
        "diary_entries": await _daily(MoodEntry, MoodEntry.created_at),
        "breath_sessions": await _daily(BreathSession, BreathSession.completed_at, BreathSession.completed == True),  # noqa: E712
        "community_posts": await _daily(CommunityPost, CommunityPost.created_at, CommunityPost.status == "active"),
    }

    # ---- 情绪：分布 + 每日全站均分 ----
    r = await db.execute(
        select(MoodEntry.mood_score, func.count(MoodEntry.id))
        .where(MoodEntry.created_at >= since)
        .group_by(MoodEntry.mood_score).order_by(MoodEntry.mood_score)
    )
    mood_distribution = [{"score": int(s), "count": c} for s, c in r.all()]
    r = await db.execute(
        select(func.date(MoodEntry.created_at).label("d"), func.avg(MoodEntry.mood_score).label("avg"))
        .where(MoodEntry.created_at >= since)
        .group_by(text("d")).order_by(text("d"))
    )
    mood_daily_avg = [{"date": str(row.d), "avg": round(float(row.avg), 2)} for row in r.all()]

    # ---- 呼吸练习排行 ----
    r = await db.execute(
        select(BreathExercise.title, func.count(BreathSession.id).label("cnt"))
        .join(BreathSession, BreathSession.exercise_id == BreathExercise.id)
        .where(BreathSession.completed == True)  # noqa: E712
        .group_by(BreathExercise.title).order_by(text("cnt DESC"))
    )
    breath_by_exercise = [{"title": t, "count": c} for t, c in r.all()]

    # ---- 对话模式分布 ----
    r = await db.execute(
        select(ChatSession.mode, func.count(ChatSession.id).label("cnt"))
        .group_by(ChatSession.mode).order_by(text("cnt DESC"))
    )
    chat_by_mode = [{"mode": m or "science", "count": c} for m, c in r.all()]

    return {"code": 0, "data": {
        "period_days": days,
        "totals": totals,
        "daily": daily,
        "mood_distribution": mood_distribution,
        "mood_daily_avg": mood_daily_avg,
        "breath_by_exercise": breath_by_exercise,
        "chat_by_mode": chat_by_mode,
    }}
