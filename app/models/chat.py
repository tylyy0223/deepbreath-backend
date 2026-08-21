"""AI 对话模型"""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, JSON, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

def _utcnow(): return datetime.now(timezone.utc)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(50), default="science")
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    user: Mapped["User"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    images: Mapped[list] = mapped_column(JSON, default=list, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    session: Mapped["ChatSession"] = relationship(back_populates="messages")

class ScaleResult(Base):
    __tablename__ = "scale_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scale_id: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_score: Mapped[int] = mapped_column(Integer, nullable=False)
    standard_score: Mapped[float] = mapped_column(nullable=False)
    level: Mapped[str] = mapped_column(String(50), default="")
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    user: Mapped["User"] = relationship(back_populates="scale_results")


class AssessmentRecord(Base):
    """心理评估结果记录（多轮对话评估的结构化落库）

    每次评估完成（AI 生成结构化总结）后保存一条，用于：
    - 用户历史评估追踪
    - 后续评估注入历史上下文（个性化）
    - 为个性化心理学专业服务提供数据基础
    """
    __tablename__ = "assessment_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    # 总体状态判断：状态良好/轻度困扰/中度困扰/需要关注
    overall_status: Mapped[str] = mapped_column(String(50), default="")
    # 风险提示：高风险/未发现紧急风险
    risk_level: Mapped[str] = mapped_column(String(20), default="")
    # 分维度概述（JSON: {"情绪": "...", "睡眠饮食": "...", ...}）
    dimensions_json: Mapped[str] = mapped_column(Text, default="{}")
    # 结构化总结全文（AI 原始输出）
    summary: Mapped[str] = mapped_column(Text, default="")
    # 建议（JSON 数组）
    suggestions_json: Mapped[str] = mapped_column(Text, default="[]")
    # 轮次统计
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    user: Mapped["User"] = relationship(back_populates="assessment_records")

from app.models.user import User  # noqa
