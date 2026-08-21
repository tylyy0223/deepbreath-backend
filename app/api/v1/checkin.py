"""签到 API — 每日签到、连续打卡、日历、统计

时间约定：所有「日」边界以 UTC+8（北京时间）00:00~24:00 为准。
签到独立于心情日记，专注行为记录和激励机制。
"""

from datetime import date, timedelta
import calendar as cal_mod
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.checkin import CheckIn
from app.schemas.checkin import (
    CheckInResult,
    CheckInStatusResult,
    CheckInCalendarResult,
    CalendarDay,
    CheckInHistoryItem,
    CheckInStatsResult,
    CheckInReward,
)
from app.services.checkin_service import (
    do_checkin,
    get_today_checkin,
    get_longest_streak,
    get_total_checkins,
    get_total_credits,
    get_month_checkins,
    get_month_and_year_counts,
    get_checkin_time_distribution,
    today_cn,
    calc_reward,
)

router = APIRouter(prefix="/api/v1/checkin", tags=["签到"])


# ====== 每日签到 ======

@router.post("")
async def checkin(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """每日签到

    规则：
    - 每天只能签到一次
    - 连续签到奖励递增：1-2天=2 Credits, 3-6天=3 Credits
    - 里程碑奖励：第7天+5, 第14天+7, 第30天+10, 第100天+20, 第365天+50
    - 中断后重新从第1天开始
    """
    result = await do_checkin(db, current_user["user_id"])
    return {"code": 0, "data": result}


# ====== 签到状态 ======

@router.get("/status")
async def checkin_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询今日签到状态 + 累计统计"""
    user_id = current_user["user_id"]
    today = today_cn()
    t = await get_today_checkin(db, user_id)
    longest = await get_longest_streak(db, user_id)
    total = await get_total_checkins(db, user_id)
    credits = await get_total_credits(db, user_id)

    # 今日预计奖励
    if t:
        current_streak = t.streak_count
        today_reward = 0
        checked = True
    else:
        # 未签到，预估今天的奖励
        from app.services.checkin_service import get_last_checkin, yesterday_cn
        last = await get_last_checkin(db, user_id)
        yday = yesterday_cn()
        if last and last.check_date == yday:
            current_streak = last.streak_count + 1
        else:
            current_streak = 1
        reward, _, _, _ = calc_reward(current_streak)
        today_reward = reward
        checked = False

    return {
        "code": 0,
        "data": {
            "checked_today": checked,
            "current_streak": current_streak,
            "longest_streak": longest,
            "total_checkins": total,
            "total_credits_earned": credits,
            "today_reward": today_reward,
        },
    }


# ====== 签到日历 ======

@router.get("/calendar")
async def checkin_calendar(
    year: int = Query(default=None, description="年份，默认今年"),
    month: int = Query(default=None, ge=1, le=12, description="月份，默认本月"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取月度签到日历（类似 GitHub 贡献图）

    返回指定月份每一天的签到状态。
    """
    user_id = current_user["user_id"]
    today = today_cn()

    if year is None:
        year = today.year
    if month is None:
        month = today.month

    # 查询当月签到记录
    records = await get_month_checkins(db, user_id, year, month)
    checked_dates = {r.check_date: r for r in records}

    # 构建日历
    _, days_in_month = cal_mod.monthrange(year, month)
    total_days = len(records)
    days = []

    for d in range(1, days_in_month + 1):
        dt = date(year, month, d)
        rec = checked_dates.get(dt)
        days.append(CalendarDay(
            date=dt.isoformat(),
            checked=rec is not None,
            streak_count=rec.streak_count if rec else 0,
        ))

    return {
        "code": 0,
        "data": {
            "year": year,
            "month": month,
            "total_days": total_days,
            "days": [d.model_dump() for d in days],
        },
    }


# ====== 签到历史 ======

@router.get("/history")
async def checkin_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """签到历史记录（分页）"""
    user_id = current_user["user_id"]
    offset = (page - 1) * page_size

    r = await db.execute(
        select(CheckIn)
        .where(CheckIn.user_id == user_id)
        .order_by(CheckIn.check_date.desc())
        .offset(offset)
        .limit(page_size)
    )
    records = r.scalars().all()

    r2 = await db.execute(
        select(func.count(CheckIn.id))
        .where(CheckIn.user_id == user_id)
    )
    total = r2.scalar() or 0

    return {
        "code": 0,
        "data": {
            "items": [
                {
                    "id": rec.id,
                    "check_date": rec.check_date.isoformat(),
                    "streak_count": rec.streak_count,
                    "credits_earned": rec.credits_earned,
                    "created_at": rec.created_at.isoformat() if rec.created_at else None,
                }
                for rec in records
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


# ====== 签到统计 ======

@router.get("/stats")
async def checkin_stats(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """个人签到统计

    包含：累计/连续/最长天数、Credits 收益、时间分布、本月本年统计
    """
    user_id = current_user["user_id"]
    total = await get_total_checkins(db, user_id)
    longest = await get_longest_streak(db, user_id)
    credits = await get_total_credits(db, user_id)
    this_month, this_year = await get_month_and_year_counts(db, user_id)
    time_dist = await get_checkin_time_distribution(db, user_id)

    # 当前连续
    t = await get_today_checkin(db, user_id)
    if t:
        current_streak = t.streak_count
    else:
        from app.services.checkin_service import get_last_checkin, yesterday_cn
        last = await get_last_checkin(db, user_id)
        yday = yesterday_cn()
        current_streak = (last.streak_count if last and last.check_date == yday else 0)

    return {
        "code": 0,
        "data": {
            "total_checkins": total,
            "current_streak": current_streak,
            "longest_streak": longest,
            "total_credits_earned": credits,
            "this_month": this_month,
            "this_year": this_year,
            **time_dist,
        },
    }
