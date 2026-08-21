"""签到业务逻辑 — 奖励计算、连续天数追踪、里程碑检测

独立于心情日记模块，专注于签到行为。
时间边界：北京时间（UTC+8）00:00 ~ 24:00
"""

from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.checkin import CheckIn

# 北京时间（UTC+8）
CN_TZ = timezone(timedelta(hours=8))


def today_cn() -> date:
    """返回北京时间今天的日期"""
    return datetime.now(CN_TZ).date()


def yesterday_cn() -> date:
    """返回北京时间昨天的日期"""
    return today_cn() - timedelta(days=1)


# ---- 奖励规则 ----
# 连续签到阶梯奖励：基础 2 Credits + 里程碑 / 加码
# key: 连续天数, value: 当日奖励 Credits

STREAK_REWARDS = [
    # (连续天数的上限, 奖励Credits, 是否里程碑)
    (1,   2, False),   # 第 1 天
    (2,   2, False),   # 第 2 天
    (3,   3, False),   # 第 3 天开始加码
    (6,   3, False),   # 第 4-6 天
    (7,   5, True),    # 第 7 天 = 一周里程碑 +5
    (13,  3, False),   # 第 8-13 天
    (14,  7, True),    # 第 14 天 = 两周里程碑 +7
    (29,  3, False),   # 第 15-29 天
    (30,  10, True),   # 第 30 天 = 一个月里程碑 +10
    (99,  3, False),   # 第 31-99 天
    (100, 20, True),   # 第 100 天里程碑 +20
    (364, 3, False),   # 第 101-364 天
    (365, 50, True),   # 第 365 天 = 一年里程碑 +50
]

MILESTONE_MESSAGES = {
    7: "🎉 连续签到一周！坚持就是胜利",
    14: "🌟 连续签到两周！你已经养成了好习惯",
    30: "🏆 连续签到一个月！自律给你自由",
    100: "👑 连续签到 100 天！你是真正的坚持者",
    365: "💎 连续签到一整年！365 天的自律传奇",
}


def calc_reward(streak: int) -> tuple[int, int, bool, str]:
    """根据连续天数计算奖励

    Returns:
        (credits, base_reward, is_milestone, message)
    """
    for max_days, reward, milestone in STREAK_REWARDS:
        if streak <= max_days:
            base = 2
            bonus = reward - base
            msg = MILESTONE_MESSAGES.get(streak, "") if milestone else ""
            return reward, base, milestone, msg

    # 超过 365 天：每 365 天一个里程碑
    base = 2
    if streak % 365 == 0:
        return 50, base, True, MILESTONE_MESSAGES[365]
    return 3, base, False, ""


async def get_last_checkin(db: AsyncSession, user_id: int) -> CheckIn | None:
    """获取用户最近一次签到记录"""
    r = await db.execute(
        select(CheckIn)
        .where(CheckIn.user_id == user_id)
        .order_by(CheckIn.check_date.desc())
        .limit(1)
    )
    return r.scalar_one_or_none()


async def get_today_checkin(db: AsyncSession, user_id: int) -> CheckIn | None:
    """获取用户今日签到记录"""
    t = today_cn()
    r = await db.execute(
        select(CheckIn).where(
            CheckIn.user_id == user_id,
            CheckIn.check_date == t,
        )
    )
    return r.scalar_one_or_none()


async def get_longest_streak(db: AsyncSession, user_id: int) -> int:
    """获取用户历史最长连续签到天数"""
    r = await db.execute(
        select(func.max(CheckIn.streak_count))
        .where(CheckIn.user_id == user_id)
    )
    return int(r.scalar() or 0)


async def get_total_checkins(db: AsyncSession, user_id: int) -> int:
    """获取用户累计签到总天数"""
    r = await db.execute(
        select(func.count(CheckIn.id))
        .where(CheckIn.user_id == user_id)
    )
    return int(r.scalar() or 0)


async def get_total_credits(db: AsyncSession, user_id: int) -> int:
    """获取用户签到累计获得的 Credits"""
    r = await db.execute(
        select(func.coalesce(func.sum(CheckIn.credits_earned), 0))
        .where(CheckIn.user_id == user_id)
    )
    return int(r.scalar() or 0)


async def get_month_checkins(db: AsyncSession, user_id: int, year: int, month: int) -> list[CheckIn]:
    """获取指定月份的签到记录"""
    from datetime import date as date_cls
    month_start = date_cls(year, month, 1)
    if month == 12:
        month_end = date_cls(year + 1, 1, 1)
    else:
        month_end = date_cls(year, month + 1, 1)

    r = await db.execute(
        select(CheckIn)
        .where(
            CheckIn.user_id == user_id,
            CheckIn.check_date >= month_start,
            CheckIn.check_date < month_end,
        )
        .order_by(CheckIn.check_date.asc())
    )
    return list(r.scalars().all())


async def get_month_and_year_counts(db: AsyncSession, user_id: int) -> tuple[int, int]:
    """获取本月和本年的签到天数"""
    t = today_cn()
    month_start = t.replace(day=1)
    year_start = t.replace(month=1, day=1)

    r_month = await db.execute(
        select(func.count(CheckIn.id))
        .where(CheckIn.user_id == user_id, CheckIn.check_date >= month_start)
    )
    r_year = await db.execute(
        select(func.count(CheckIn.id))
        .where(CheckIn.user_id == user_id, CheckIn.check_date >= year_start)
    )
    return int(r_month.scalar() or 0), int(r_year.scalar() or 0)


async def get_checkin_time_distribution(db: AsyncSession, user_id: int) -> dict[str, int]:
    """统计用户签到时间分布（按时段，按北京时间切小时）"""
    _cn_hour = func.extract("hour", CheckIn.created_at.op("AT TIME ZONE")("Asia/Shanghai"))
    r = await db.execute(
        select(
            _cn_hour.label("hour"),
            func.count(CheckIn.id).label("cnt"),
        )
        .where(CheckIn.user_id == user_id)
        .group_by(_cn_hour)
    )
    rows = r.all()
    morning = afternoon = evening = night = 0
    for hour, cnt in rows:
        h = int(hour)
        if 6 <= h < 12:
            morning += cnt
        elif 12 <= h < 18:
            afternoon += cnt
        elif 18 <= h < 24:
            evening += cnt
        else:
            night += cnt
    return {
        "morning_count": morning,
        "afternoon_count": afternoon,
        "evening_count": evening,
        "night_count": night,
    }


async def do_checkin(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """执行签到

    Returns:
        dict with keys: checked, streak, reward_credits, is_milestone, message,
                        longest_streak, total_checkins, total_credits
    """
    t = today_cn()

    # 1. 检查今日是否已签到
    existing = await get_today_checkin(db, user_id)
    if existing:
        return {
            "checked": True,
            "streak": existing.streak_count,
            "reward_credits": 0,
            "is_milestone": False,
            "message": "今日已签到，明天再来吧~",
            "longest_streak": await get_longest_streak(db, user_id),
            "total_checkins": await get_total_checkins(db, user_id),
            "total_credits": await get_total_credits(db, user_id),
        }

    # 2. 计算连续天数
    last = await get_last_checkin(db, user_id)
    yesterday = yesterday_cn()
    if last and last.check_date == yesterday:
        streak = last.streak_count + 1
    elif last and last.check_date == t:
        # 同一天重复签到（刚才逻辑已处理，兜底）
        streak = last.streak_count
    else:
        # 中断了，重新开始
        streak = 1

    # 3. 计算奖励
    reward_credits, base_reward, is_milestone, msg = calc_reward(streak)

    # 4. 记录签到
    checkin = CheckIn(
        user_id=user_id,
        check_date=t,
        streak_count=streak,
        credits_earned=reward_credits,
    )
    db.add(checkin)

    # 5. 发放 Credits
    from app.services.credits_service import add_transaction
    try:
        await add_transaction(
            db, user_id, reward_credits, "reward",
            ref=f"checkin:{t.isoformat()}",
            note=f"每日签到奖励 (连续第{streak}天)",
        )
    except Exception:
        pass

    await db.flush()

    # 6. 构造返回
    message = msg or f"签到成功！连续第 {streak} 天，获得 {reward_credits} Credits"

    return {
        "checked": True,
        "streak": streak,
        "reward_credits": reward_credits,
        "is_milestone": is_milestone,
        "message": message,
        "longest_streak": max(streak, await get_longest_streak(db, user_id)),
        "total_checkins": await get_total_checkins(db, user_id),
        "total_credits": await get_total_credits(db, user_id),
    }
