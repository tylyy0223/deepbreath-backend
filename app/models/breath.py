"""呼吸练习模型"""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def _utcnow(): return datetime.now(timezone.utc)

class BreathExercise(Base):
    __tablename__ = "breath_exercises"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    technique_type: Mapped[str] = mapped_column(String(50), nullable=False)  # box_breathing, 478, etc.
    duration_sec: Mapped[int] = mapped_column(Integer, default=60)
    audio_url: Mapped[str] = mapped_column(String(500), default="")
    animation_config: Mapped[str] = mapped_column(Text, default="{}")  # JSON for animation
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

class BreathSession(Base):
    __tablename__ = "breath_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_id: Mapped[int] = mapped_column(Integer, ForeignKey("breath_exercises.id"), nullable=True)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
