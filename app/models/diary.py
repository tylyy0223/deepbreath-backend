"""日记模型 — MoodEntry"""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MoodEntry(Base):
    __tablename__ = "mood_entries"
    user: Mapped["User"] = relationship(back_populates="diary_entries")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    mood_score: Mapped[int] = mapped_column(Integer, nullable=False)
    mood_label: Mapped[str] = mapped_column(String(100), default="")
    body_sensation: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    weather: Mapped[str] = mapped_column(String(50), default="")
    images: Mapped[list] = mapped_column(JSON, default=list, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self):
        return f"<MoodEntry user={self.user_id} score={self.mood_score}>"

from sqlalchemy.orm import relationship
