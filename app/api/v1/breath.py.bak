"""呼吸练习 API"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta, date
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.breath import BreathExercise, BreathSession

router = APIRouter(prefix="/api/v1/breath", tags=["呼吸练习"])


@router.get("/exercises")
async def list_exercises(db: AsyncSession = Depends(get_db)):
    """呼吸练习列表"""
    r = await db.execute(
        select(BreathExercise).where(BreathExercise.status == "active").order_by(BreathExercise.sort_order)
    )
    exercises = r.scalars().all()
    return {"code": 0, "data": [
        {"id": e.id, "title": e.title, "description": e.description,
         "technique_type": e.technique_type, "duration_sec": e.duration_sec,
         "audio_url": e.audio_url, "animation_config": e.animation_config}
        for e in exercises
    ]}


@router.get("/exercises/{exercise_id}")
async def get_exercise(exercise_id: int, db: AsyncSession = Depends(get_db)):
    """呼吸练习详情"""
    r = await db.execute(select(BreathExercise).where(BreathExercise.id == exercise_id))
    e = r.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="练习不存在")
    return {"code": 0, "data": {"id": e.id, "title": e.title, "description": e.description, "technique_type": e.technique_type, "duration_sec": e.duration_sec, "audio_url": e.audio_url, "animation_config": e.animation_config}}


class BreathComplete(BaseModel):
    exercise_id: int
    duration_sec: int
    completed: bool = True


@router.post("/complete")
async def complete_exercise(
    req: BreathComplete,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """记录完成一次呼吸练习"""
    session = BreathSession(
        user_id=current_user["user_id"],
        exercise_id=req.exercise_id,
        duration_sec=req.duration_sec,
        completed=req.completed,
        completed_at=datetime.now(timezone.utc) if req.completed else None,
    )
    db.add(session)
    await db.flush()
    return {"code": 0, "message": "已记录", "data": {"session_id": session.id}}


@router.get("/history")
async def practice_history(
    limit: int = Query(default=20, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户的呼吸练习历史记录"""
    r = await db.execute(
        select(BreathSession, BreathExercise.title)
        .outerjoin(BreathExercise, BreathSession.exercise_id == BreathExercise.id)
        .where(BreathSession.user_id == current_user["user_id"])
        .order_by(BreathSession.started_at.desc())
        .limit(limit)
    )
    rows = r.all()
    return {"code": 0, "data": [
        {"id": s.id, "exercise_id": s.exercise_id, "exercise_title": title or "呼吸练习",
         "duration_sec": s.duration_sec, "completed": s.completed,
         "completed_at": s.completed_at.isoformat() if s.completed_at else None,
         "started_at": s.started_at.isoformat() if s.started_at else None}
        for s, title in rows
    ]}


@router.get("/stats")
async def practice_stats(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户的呼吸练习统计：累计次数/时长、连续天数、本周次数"""
    user_id = current_user["user_id"]
    now = datetime.now(timezone.utc)

    r = await db.execute(
        select(func.count(BreathSession.id), func.coalesce(func.sum(BreathSession.duration_sec), 0))
        .where(BreathSession.user_id == user_id, BreathSession.completed == True)  # noqa: E712
    )
    total_sessions, total_sec = r.one()

    week_start = now - timedelta(days=7)
    r2 = await db.execute(
        select(func.count(BreathSession.id))
        .where(BreathSession.user_id == user_id, BreathSession.completed == True,  # noqa: E712
               BreathSession.completed_at >= week_start)
    )
    week_sessions = r2.scalar() or 0

    # 连续天数：取去重的练习日期，从今天（或昨天）往前数连续
    r3 = await db.execute(
        select(func.date(BreathSession.completed_at))
        .where(BreathSession.user_id == user_id, BreathSession.completed == True)  # noqa: E712
        .distinct()
    )
    days = {d for (d,) in r3.all() if d is not None}
    days = {d if isinstance(d, date) else datetime.strptime(str(d), "%Y-%m-%d").date() for d in days}
    streak = 0
    cursor = now.date()
    if cursor not in days:
        cursor -= timedelta(days=1)  # 今天还没练，从昨天起算
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)

    return {"code": 0, "data": {
        "total_sessions": int(total_sessions or 0),
        "total_minutes": round(int(total_sec or 0) / 60),
        "streak_days": streak,
        "week_sessions": int(week_sessions),
    }}
