"""QA 缓存模型 — 永久持久化"""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text, BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def _utcnow(): return datetime.now(timezone.utc)

class QACache(Base):
    __tablename__ = "qa_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # MD5
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_hit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("idx_qa_mode_hash", "mode", "question_hash", unique=True),
    )


class UserQACache(Base):
    """用户提问记录 — 个性化服务"""
    __tablename__ = "user_qa_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("idx_uqa_user_hash", "user_id", "question_hash"),
    )


class BookProgress(Base):
    """用户读书进度（取代旧 SQLite reading_progress）"""
    __tablename__ = "book_progress"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    book_title: Mapped[str] = mapped_column(String(200), nullable=False)
    book_path: Mapped[str] = mapped_column(String(500), default="")
    total_chapters: Mapped[int] = mapped_column(Integer, default=1)
    current_chapter: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("idx_bp_user_book", "user_id", "book_title", unique=True),
    )


class UserAudioCache(Base):
    """用户音频缓存 — 个性化 TTS"""
    __tablename__ = "user_audio_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    play_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("idx_uac_user_hash", "user_id", "text_hash"),
    )
