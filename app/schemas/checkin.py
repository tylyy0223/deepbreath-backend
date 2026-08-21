"""签到请求/响应结构 — 独立于日记模块"""
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


# ---- 请求 ----

class CheckInRequest(BaseModel):
    """签到请求（无额外参数，用户身份由 token 确定）"""
    pass


# ---- 响应 ----

class CheckInReward(BaseModel):
    """签到奖励信息"""
    credits: int = Field(..., description="本次获得的 Credits 数量")
    base_reward: int = Field(..., description="基础奖励")
    streak_bonus: int = Field(default=0, description="连续签到额外奖励")


class CheckInResult(BaseModel):
    """签到结果"""
    checked: bool = Field(..., description="是否已签到")
    streak: int = Field(..., description="当前连续签到天数")
    reward: CheckInReward | None = Field(default=None, description="本次奖励（已签到时为 null）")
    is_milestone: bool = Field(default=False, description="是否为里程碑日（7/14/30/100/365 天）")
    message: str = Field(default="", description="提示信息")


class CheckInStatusResult(BaseModel):
    """签到状态查询结果"""
    checked_today: bool = Field(..., description="今日是否已签到")
    current_streak: int = Field(..., description="当前连续签到天数")
    longest_streak: int = Field(..., description="历史最长连续天数")
    total_checkins: int = Field(..., description="累计签到总天数")
    total_credits_earned: int = Field(..., description="签到累计获得 Credits")
    today_reward: int = Field(default=0, description="今日预计奖励 Credits 数")


class CalendarDay(BaseModel):
    """日历中的一天"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    checked: bool = Field(default=False, description="是否已签到")
    streak_count: int = Field(default=0, description="当天的连续天数")


class CheckInCalendarResult(BaseModel):
    """签到日历"""
    year: int
    month: int
    total_days: int = Field(..., description="本月签到天数")
    days: list[CalendarDay] = Field(default_factory=list)


class CheckInHistoryItem(BaseModel):
    """签到历史中的一条"""
    id: int
    check_date: str
    streak_count: int
    credits_earned: int
    created_at: str


class CheckInStatsResult(BaseModel):
    """签到统计"""
    total_checkins: int = Field(..., description="累计签到总天数")
    current_streak: int = Field(..., description="当前连续签到天数")
    longest_streak: int = Field(..., description="历史最长连续天数")
    total_credits_earned: int = Field(..., description="累计签到获得 Credits")
    this_month: int = Field(..., description="本月签到天数")
    this_year: int = Field(..., description="本年签到天数")
    # 签到习惯
    morning_count: int = Field(default=0, description="上午(6-12点)签到次数")
    afternoon_count: int = Field(default=0, description="下午(12-18点)签到次数")
    evening_count: int = Field(default=0, description="晚上(18-24点)签到次数")
    night_count: int = Field(default=0, description="深夜(0-6点)签到次数")
