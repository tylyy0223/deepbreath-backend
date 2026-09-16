"""Credits 计费服务 — 定价、余额、扣费、入账"""
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.redis import redis_client
from app.models.credits import CreditTransaction

# 余额缓存 TTL (秒). 写流水时主动 invalidate
BALANCE_CACHE_TTL = 60

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


async def get_balance(db, user_id, *, use_cache=True):
    cache_key = f"user:balance:{user_id}"
    if use_cache:
        try:
            cached = await redis_client.get(cache_key)
            if cached is not None:
                return int(cached)
        except Exception:
            pass
    r = await db.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0))
        .where(CreditTransaction.user_id == user_id)
    )
    balance = int(r.scalar() or 0)
    if use_cache:
        try:
            await redis_client.set(cache_key, balance, ex=BALANCE_CACHE_TTL)
        except Exception:
            pass
    return balance


async def _invalidate_balance_cache(user_id):
    try:
        await redis_client.delete(f"user:balance:{user_id}")
    except Exception:
        pass


async def add_transaction(
    db: AsyncSession, user_id: int, amount: int, type: str,
    ref: str = "", note: str = "",
) -> CreditTransaction:
    balance = await get_balance(db, user_id, use_cache=False)
    tx = CreditTransaction(
        user_id=user_id, amount=amount, type=type, ref=ref, note=note,
        balance_after=balance + amount,
    )
    db.add(tx)
    await db.flush()
    await _invalidate_balance_cache(user_id)
    return tx


async def charge(db: AsyncSession, user_id: int, cost: int, ref: str = "", note: str = "") -> bool:
    """扣费：余额足够返回 True 并写流水；不足返回 False

    并发安全: 用 pg_advisory_xact_lock(user_id) 在事务级串行化同一用户的扣费。
    避免两个并发请求都查到 balance=100 都判断通过、都写 -80 的流水导致实际余额 -60。
    lock 在事务结束时 (commit/rollback) 自动释放。
    """
    if cost <= 0:
        return True
    # PG advisory lock 基于 user_id (事务级串行化, 防 check-then-act 竞态)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:uid)"),
        {"uid": user_id},
    )
    # 锁内必须实时算 (use_cache=False), 缓存可能 stale; 末尾 invalidate 保证后续读最新
    balance = await get_balance(db, user_id, use_cache=False)
    if balance < cost:
        return False
    db.add(CreditTransaction(
        user_id=user_id, amount=-cost, type="consume", ref=ref, note=note,
        balance_after=balance - cost,
    ))
    await db.flush()
    await _invalidate_balance_cache(user_id)
    return True
