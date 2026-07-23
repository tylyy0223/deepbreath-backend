"""日记 API — 创建 / 列表 / 统计 / 详情 / 编辑 / 删除"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field
from datetime import date
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.diary import MoodEntry  # noqa: E402

router = APIRouter(prefix="/api/v1/diary", tags=["日记"])


class DiaryCreateRequest(BaseModel):
    mood_score: int = Field(..., ge=1, le=5)
    mood_label: str = ""
    body_sensation: str = ""
    note: str = ""
    weather: str = ""


class DiaryUpdateRequest(BaseModel):
    mood_score: Optional[int] = Field(None, ge=1, le=5)
    mood_label: Optional[str] = None
    body_sensation: Optional[str] = None
    note: Optional[str] = None
    weather: Optional[str] = None


def _entry_json(entry: MoodEntry) -> dict:
    return {
        "id": entry.id,
        "mood_score": entry.mood_score,
        "mood_label": entry.mood_label,
        "body_sensation": entry.body_sensation,
        "note": entry.note,
        "weather": entry.weather,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.post("/create")
async def create_diary(
    req: DiaryCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建日记"""
    entry = MoodEntry(
        user_id=current_user["user_id"],
        mood_score=req.mood_score,
        mood_label=req.mood_label,
        body_sensation=req.body_sensation,
        note=req.note,
        weather=req.weather,
    )
    db.add(entry)
    await db.flush()
    return {"code": 0, "data": {"id": entry.id}}


@router.get("/list")
async def list_diary(
    days: int = Query(default=7, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取最近 N 天的日记列表"""
    r = await db.execute(
        select(MoodEntry)
        .where(MoodEntry.user_id == current_user["user_id"])
        .order_by(MoodEntry.created_at.desc())
        .limit(days * 5)  # rough upper bound
    )
    entries = r.scalars().all()
    return {"code": 0, "data": [_entry_json(e) for e in entries]}


@router.get("/stats")
async def diary_stats(
    days: int = Query(default=30, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """日记统计（含连续天数、常见情绪、情绪分布）"""
    from datetime import datetime, timezone, timedelta

    user_id = current_user["user_id"]
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 基础统计
    r = await db.execute(
        select(
            func.avg(MoodEntry.mood_score),
            func.count(MoodEntry.id),
        ).where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since)
    )
    avg_mood, total = r.one()

    # 连续记录天数：从今天往回数，直到遇到没有记录的那天
    streak = 0
    today = datetime.now(timezone.utc).date()
    for i in range(365):
        d = today - timedelta(days=i)
        cnt = (await db.execute(
            select(func.count(MoodEntry.id)).where(
                MoodEntry.user_id == user_id,
                func.date(MoodEntry.created_at) == d
            )
        )).scalar() or 0
        if cnt > 0:
            streak += 1
        else:
            break

    # 常见情绪标签
    r2 = await db.execute(
        select(MoodEntry.mood_label, func.count(MoodEntry.id).label("cnt"))
        .where(MoodEntry.user_id == user_id, MoodEntry.mood_label != "", MoodEntry.created_at >= since)
        .group_by(MoodEntry.mood_label)
        .order_by(func.count(MoodEntry.id).desc())
        .limit(1)
    )
    top_label = r2.first()
    most_common = top_label[0] if top_label else None

    # 情绪分布（mood_score 1-5 各出现次数）
    r3 = await db.execute(
        select(MoodEntry.mood_score, func.count(MoodEntry.id))
        .where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since)
        .group_by(MoodEntry.mood_score)
    )
    distribution = {int(row[0]): row[1] for row in r3.fetchall()}

    return {
        "code": 0,
        "data": {
            "average_mood": round(float(avg_mood), 2) if avg_mood else None,
            "total_entries": total or 0,
            "streak_days": streak,
            "most_common_label": most_common,
            "mood_distribution": distribution,
        },
    }


@router.get("/{entry_id}")
async def get_diary_entry(
    entry_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取单条日记详情"""
    r = await db.execute(
        select(MoodEntry).where(
            MoodEntry.id == entry_id,
            MoodEntry.user_id == current_user["user_id"],
        )
    )
    entry = r.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="日记不存在")
    return {"code": 0, "data": _entry_json(entry)}


@router.put("/{entry_id}")
async def update_diary_entry(
    entry_id: int,
    req: DiaryUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑日记（仅允许修改自己的日记）"""
    r = await db.execute(
        select(MoodEntry).where(
            MoodEntry.id == entry_id,
            MoodEntry.user_id == current_user["user_id"],
        )
    )
    entry = r.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="日记不存在")

    # Only update fields that were explicitly provided
    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(entry, field, value)

    await db.flush()
    return {"code": 0, "data": _entry_json(entry)}


@router.delete("/{entry_id}")
async def delete_diary_entry(
    entry_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除日记（仅允许删除自己的日记）"""
    r = await db.execute(
        select(MoodEntry).where(
            MoodEntry.id == entry_id,
            MoodEntry.user_id == current_user["user_id"],
        )
    )
    entry = r.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="日记不存在")

    await db.delete(entry)
    await db.flush()
    return {"code": 0, "data": {"id": entry_id, "deleted": True}}


# ====== P1-#10: 个人周报 MVP ======

@router.get("/weekly-report")
async def weekly_report(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """近 7 天数据聚合：情绪走势、日记/呼吸统计（无 AI 总结）"""
    from datetime import datetime, timezone, timedelta
    from app.models.breath import BreathSession

    user_id = current_user["user_id"]
    since = datetime.now(timezone.utc) - timedelta(days=7)

    # 情绪数据：近7天每日均分
    mood_rows = (await db.execute(
        select(func.date(MoodEntry.created_at).label("d"), func.avg(MoodEntry.mood_score).label("avg"))
        .where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since)
        .group_by(func.date(MoodEntry.created_at))
        .order_by(func.date(MoodEntry.created_at))
    )).all()

    mood_trend = [
        {"date": str(r.d), "avg_mood": round(float(r.avg), 1)}
        for r in mood_rows
    ]

    # 日记总数
    diary_count = (await db.execute(
        select(func.count(MoodEntry.id)).where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since)
    )).scalar() or 0

    # 呼吸统计
    breath_rows = (await db.execute(
        select(func.count(BreathSession.id), func.coalesce(func.sum(BreathSession.duration_sec), 0))
        .where(BreathSession.user_id == user_id, BreathSession.completed == True,  # noqa: E712
               BreathSession.completed_at >= since)
    )).first()

    return {"code": 0, "data": {
        "mood_trend": mood_trend,
        "diary_count": diary_count,
        "breath_count": breath_rows[0] or 0,
        "breath_minutes": round((breath_rows[1] or 0) / 60, 1),
        "week_start": since.isoformat(),
    }}
