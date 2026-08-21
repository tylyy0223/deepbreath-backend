"""签到模型 — 每日签到、连续打卡、里程碑奖励

独立于心情日记模块，专注签到行为记录和连续天数追踪。
"""
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, DateTime, Date, BigInteger, Boolean, Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class CheckIn(Base):
    """每日签到记录

    每条记录 = 用户在某一天的一次签到。
    streak_count 记录截至该天的连续签到天数。
    """
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    check_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    streak_count: Mapped[int] = mapped_column(Integer, default=1)
    credits_earned: Mapped[int] = mapped_column(Integer, default=0)  # 本次签到获得的 Credits
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("idx_checkins_user_date", "user_id", "check_date", unique=True),
        Index("idx_checkins_date", "check_date"),
    )

    def __repr__(self):
        return f"<CheckIn user={self.user_id} date={self.check_date} streak={self.streak_count}>"
