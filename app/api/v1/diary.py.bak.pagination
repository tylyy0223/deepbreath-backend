"""日记 API — 创建 / 列表 / 统计 / 详情 / 编辑 / 删除 / 周报

时间约定：所有「日」边界以 UTC+8（北京时间）00:00~24:00 为准；
「周」边界以自然周 周一 00:00 ~ 周日 24:00 为准。

注意：签到功能已拆分至独立的 `/api/v1/checkin` 模块。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from pydantic import BaseModel, Field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.diary import MoodEntry  # noqa: E402

router = APIRouter(prefix="/api/v1/diary", tags=["日记"])

# 北京时间时区（UTC+8）
CN_TZ = timezone(timedelta(hours=8))

# 标准情绪档位（与前端 MOOD_EMOJIS 一致）——统计"常见情绪"用评分映射，
# 不统计自由文本 mood_label（用户乱填如"签到""热"导致数据失真）
_SCORE_LABELS = {
    1: "很糟糕",
    2: "不太好",
    3: "一般般",
    4: "还不错",
    5: "很开心",
}


def _today_cn() -> date:
    """返回北京时间今天的日期"""
    return datetime.now(CN_TZ).date()


def _current_week_range():
    """返回本周一 00:00:00 ~ 下周一 00:00:00（北京时间）"""
    now = datetime.now(CN_TZ)
    monday = now.date() - timedelta(days=now.weekday())
    week_start = datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=CN_TZ)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


# ====== 日记 CRUD ======

class DiaryCreateRequest(BaseModel):
    mood_score: int = Field(..., ge=1, le=5)
    mood_label: str = ""
    body_sensation: str = ""
    note: str = ""
    weather: str = ""
    images: list[str] = []


class DiaryUpdateRequest(BaseModel):
    mood_score: Optional[int] = Field(None, ge=1, le=5)
    mood_label: Optional[str] = None
    body_sensation: Optional[str] = None
    note: Optional[str] = None
    weather: Optional[str] = None
    images: Optional[list[str]] = None


def _entry_json(entry: MoodEntry) -> dict:
    return {
        "id": entry.id,
        "mood_score": entry.mood_score,
        "mood_label": entry.mood_label,
        "body_sensation": entry.body_sensation,
        "note": entry.note,
        "weather": entry.weather,
        "images": getattr(entry, 'images', None) or [],
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
        images=req.images or [],
    )
    db.add(entry)
    await db.flush()
    return {"code": 0, "data": {"id": entry.id}}


@router.get("/list")
async def list_diary(
    days: int = Query(default=7, ge=1, le=365),
    search: str = Query(default=""),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取最近 N 天的日记列表，支持按关键词搜索 note 和 mood_label"""
    q = select(MoodEntry).where(MoodEntry.user_id == current_user["user_id"])
    await db.execute(text("SET TIME ZONE 'Asia/Shanghai'"))
    if search:
        pattern = f"%{search}%"
        q = q.where(
            MoodEntry.note.ilike(pattern) | MoodEntry.mood_label.ilike(pattern)
        )
    q = q.order_by(MoodEntry.created_at.desc()).limit(days * 5)
    r = await db.execute(q)
    entries = r.scalars().all()
    return {"code": 0, "data": [_entry_json(e) for e in entries]}


@router.get("/stats")
async def diary_stats(
    days: int = Query(default=30, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """日记统计（含连续天数、常见情绪、情绪分布）

    时间边界以北京时间（UTC+8）为准；不使用连接级 SET TIME ZONE
    （asyncpg 连接池轮换会导致时区丢失），改为 SQL 内联 AT TIME ZONE 转换。
    常见情绪基于标准评分档位（1-5），不再统计自由文本 mood_label。
    """
    from datetime import datetime, timezone as _tz, timedelta as _td

    user_id = current_user["user_id"]
    since = datetime.now(CN_TZ) - _td(days=days)
    today_cn = _today_cn()

    # 1) 平均心情 + 总记录数（days 天内）
    r = await db.execute(
        select(
            func.avg(MoodEntry.mood_score),
            func.count(MoodEntry.id),
        ).where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since)
    )
    avg_mood, total = r.one()

    # 2) 连续记录天数：从今天（北京时间）往回逐日检查，断档即停。
    #    用 (created_at AT TIME ZONE 'Asia/Shanghai')::date 保证按北京时间切日，
    #    不依赖连接时区。
    streak = 0
    for i in range(min(365, days + 1)):
        d = today_cn - _td(days=i)
        cnt = (await db.execute(
            select(func.count(MoodEntry.id)).where(
                MoodEntry.user_id == user_id,
                func.date(MoodEntry.created_at.op("AT TIME ZONE")("Asia/Shanghai")) == d,
            )
        )).scalar() or 0
        if cnt > 0:
            streak += 1
        else:
            break

    # 3) 常见情绪：基于 mood_score 的标准情绪档位（1=很糟糕 … 5=很开心），
    #    取最高频档位的名称（自由文本 mood_label 不参与统计）。
    r2 = await db.execute(
        select(MoodEntry.mood_score, func.count(MoodEntry.id).label("cnt"))
        .where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since)
        .group_by(MoodEntry.mood_score)
        .order_by(func.count(MoodEntry.id).desc())
        .limit(1)
    )
    top_score_row = r2.first()
    most_common_label = None
    if top_score_row:
        most_common_label = _SCORE_LABELS.get(int(top_score_row[0]))

    # 4) 情绪分布：按评分统计
    r3 = await db.execute(
        select(MoodEntry.mood_score, func.count(MoodEntry.id))
        .where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since)
        .group_by(MoodEntry.mood_score)
    )
    distribution = {int(row[0]): row[1] for row in r3.fetchall()}

    return {
        "code": 0,
        "data": {
            "average_mood": round(float(avg_mood), 2) if avg_mood is not None else None,
            "total_entries": total or 0,
            "streak_days": streak,
            "most_common_label": most_common_label,
            "mood_distribution": distribution,
            "days": days,
        },
    }


@router.get("/weekly-report")
async def weekly_report(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """本周数据聚合：情绪、日记、呼吸、签到、AI 对话、Credits

    周边界：自然周 周一 00:00 ~ 周日 24:00（北京时间）
    """
    from app.models.breath import BreathSession
    from app.models.chat import ChatSession, ChatMessage
    from app.models.checkin import CheckIn
    from app.models.credits import CreditTransaction

    user_id = current_user["user_id"]
    since, until = _current_week_range()

    # ---- 情绪趋势（按北京时间切日，不依赖连接时区）----
    _cn_date = MoodEntry.created_at.op("AT TIME ZONE")("Asia/Shanghai")
    mood_rows = (await db.execute(
        select(
            func.date(_cn_date).label("d"),
            func.avg(MoodEntry.mood_score).label("avg"),
        )
        .where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since, MoodEntry.created_at < until)
        .group_by(func.date(_cn_date))
        .order_by(func.date(_cn_date))
    )).all()
    mood_trend = [
        {"date": str(r.d), "avg_mood": round(float(r.avg), 1)}
        for r in mood_rows
    ]

    diary_count = (await db.execute(
        select(func.count(MoodEntry.id))
        .where(MoodEntry.user_id == user_id, MoodEntry.created_at >= since, MoodEntry.created_at < until)
    )).scalar() or 0

    breath_rows = (await db.execute(
        select(
            func.count(BreathSession.id),
            func.coalesce(func.sum(BreathSession.duration_sec), 0),
        )
        .where(
            BreathSession.user_id == user_id,
            BreathSession.completed == True,  # noqa: E712
            BreathSession.completed_at >= since,
            BreathSession.completed_at < until,
        )
    )).first()

    checkin_rows = (await db.execute(
        select(
            func.count(CheckIn.id),
            func.coalesce(func.sum(CheckIn.credits_earned), 0),
            func.max(CheckIn.streak_count),
        )
        .where(CheckIn.user_id == user_id, CheckIn.check_date >= since.date(), CheckIn.check_date < until.date())
    )).first()

    chat_mode_rows = (await db.execute(
        select(
            ChatSession.mode,
            func.count(ChatSession.id).label("sessions"),
            func.coalesce(func.sum(ChatSession.message_count), 0).label("messages"),
        )
        .where(ChatSession.user_id == user_id, ChatSession.created_at >= since, ChatSession.created_at < until)
        .group_by(ChatSession.mode)
    )).all()
    chat_by_mode = [
        {
            "mode": r.mode,
            "label": CHAT_MODE_LABELS.get(r.mode, r.mode),
            "sessions": r.sessions,
            "messages": r.messages,
        }
        for r in chat_mode_rows
    ]
    total_chat_sessions = sum(r.sessions for r in chat_mode_rows)
    total_chat_messages = sum(r.messages for r in chat_mode_rows)

    credit_earned = (await db.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0))
        .where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.created_at >= since,
            CreditTransaction.created_at < until,
            CreditTransaction.amount > 0,
        )
    )).scalar() or 0

    credit_spent = (await db.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0))
        .where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.created_at >= since,
            CreditTransaction.created_at < until,
            CreditTransaction.amount < 0,
        )
    )).scalar() or 0

    return {
        "code": 0,
        "data": {
            "week_start": since.isoformat(),
            "week_end": until.isoformat(),
            "mood_trend": mood_trend,
            "diary_count": diary_count,
            "breath_count": int(breath_rows[0] or 0),
            "breath_minutes": round(float(breath_rows[1] or 0) / 60, 1),
            "checkin_days": int(checkin_rows[0] or 0),
            "checkin_credits": int(checkin_rows[1] or 0),
            "checkin_max_streak": int(checkin_rows[2] or 0),
            "chat_by_mode": chat_by_mode,
            "total_chat_sessions": total_chat_sessions,
            "total_chat_messages": total_chat_messages,
            "credit_earned": credit_earned,
            "credit_spent": abs(credit_spent),
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

    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "images" and value is None:
            continue  # 不传 images 则保留原值
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


