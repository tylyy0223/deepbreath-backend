"""Credits 计费模型 — 流水 / 订单 / 兑换码"""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def _utcnow(): return datetime.now(timezone.utc)


class CreditTransaction(Base):
    """Credits 流水：余额 = SUM(amount)，只增不删，可审计"""
    __tablename__ = "credit_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # 正=入账，负=消费
    type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # gift/consume/recharge/adjust/redeem/refund
    ref: Mapped[str] = mapped_column(String(100), default="")  # 业务关联：chat:<session_id> / tts / email / order:<no> / code:<code>
    note: Mapped[str] = mapped_column(String(200), default="")
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class CreditOrder(Base):
    """充值订单"""
    __tablename__ = "credit_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False)  # 金额（分）
    credits: Mapped[int] = mapped_column(Integer, nullable=False)     # 到账 Credits（含加赠）
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # wechat/alipay/card/corporate
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending/paid/delivered/cancelled/refunded
    proof: Mapped[str] = mapped_column(Text, default="")  # 对公转账凭证（用户提交）
    handled_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)  # 核销管理员
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class RedeemCode(Base):
    """兑换码"""
    __tablename__ = "redeem_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
