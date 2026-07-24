"""Credits 计费服务 — 定价、余额、扣费、入账"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.credits import CreditTransaction

# ==== 定价（单位：Credit，1 Credit = ¥0.01）====
PRICING = {
    "chat_science": 1,      # AI 对话 · 心理科普
    "chat_reading": 1,      # AI 对话 · 阅读模式
    "chat_counseling": 2,   # AI 对话 · 心理树洞
    "chat_assessment": 2,   # AI 对话 · 心理评估
    "tts": 15,              # TTS 语音朗读（缓存命中不扣）
    "email": 5,             # 邮件发送
    "scale": 20,            # 心理量表测评
}

PRICING_LABELS = [
    {"key": "chat_science", "label": "AI 对话 · 心理科普/阅读", "cost": 1, "unit": "条"},
    {"key": "chat_counseling", "label": "AI 对话 · 心理树洞/评估", "cost": 2, "unit": "条"},
    {"key": "tts", "label": "语音朗读（缓存命中免费）", "cost": 15, "unit": "次"},
    {"key": "email", "label": "邮件发送", "cost": 5, "unit": "封"},
    {"key": "scale", "label": "心理量表测评（SDS/SAS/SCL-90）", "cost": 20, "unit": "次"},
    {"key": "free", "label": "呼吸练习 / 情绪日记 / 社区 / 文章", "cost": 0, "unit": ""},
]

# ==== 充值档位（amount_fen 单位：分）====
PACKAGES = [
    {"id": "starter", "name": "入门", "amount_fen": 600, "credits": 600},
    {"id": "standard", "name": "标准", "amount_fen": 1800, "credits": 2000},
    {"id": "value", "name": "优惠", "amount_fen": 5000, "credits": 6000},
    {"id": "premium", "name": "畅享", "amount_fen": 9800, "credits": 12500},
]

# 对公转账收款信息（占位：商户资质申请中，待补充）
CORPORATE_ACCOUNT = {
    "company": "XX公司（占位，待补充）",
    "bank": "XX银行 XX支行（待补充）",
    "account_no": "待补充",
    "note": "转账时请备注订单号；到账后 1 个工作日内人工核销发放",
}

REGISTER_GIFT = 1000  # 注册赠送


def chat_cost(mode: str) -> int:
    return PRICING.get(f"chat_{mode}", PRICING["chat_science"])


async def get_balance(db: AsyncSession, user_id: int) -> int:
    r = await db.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0))
        .where(CreditTransaction.user_id == user_id)
    )
    return int(r.scalar() or 0)


async def add_transaction(
    db: AsyncSession, user_id: int, amount: int, type: str,
    ref: str = "", note: str = "",
) -> CreditTransaction:
    """写一条流水（不做余额校验，调用方负责）"""
    balance = await get_balance(db, user_id)
    tx = CreditTransaction(
        user_id=user_id, amount=amount, type=type, ref=ref, note=note,
        balance_after=balance + amount,
    )
    db.add(tx)
    await db.flush()
    return tx


async def charge(db: AsyncSession, user_id: int, cost: int, ref: str = "", note: str = "") -> bool:
    """扣费：余额足够返回 True 并写流水；不足返回 False"""
    if cost <= 0:
        return True
    balance = await get_balance(db, user_id)
    if balance < cost:
        return False
    db.add(CreditTransaction(
        user_id=user_id, amount=-cost, type="consume", ref=ref, note=note,
        balance_after=balance - cost,
    ))
    await db.flush()
    return True
