"""Credits API — 余额/流水/价目/充值订单/兑换码 + 管理端"""
import secrets
import string
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field
from app.core.database import get_db
from app.core.security import get_current_user, require_role, Roles
from app.models.credits import CreditTransaction, CreditOrder, RedeemCode
from app.models.user import User
from app.services.credits_service import (
    PRICING_LABELS, PACKAGES, CORPORATE_ACCOUNT,
    get_balance, add_transaction,
)

router = APIRouter(prefix="/api/v1/credits", tags=["Credits"])

CHANNELS = ("wechat", "alipay", "card", "corporate")
# 商户号申请中：官方支付渠道暂为占位，仅对公转账可用
CHANNEL_READY = {"wechat": False, "alipay": False, "card": False, "corporate": True}


# ==================== 用户端 ====================

@router.get("/balance")
async def balance(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """当前余额"""
    return {"code": 0, "data": {"balance": await get_balance(db, current_user["user_id"])}}


@router.get("/pricing")
async def pricing():
    """价目表 + 充值档位 + 渠道状态"""
    return {"code": 0, "data": {
        "pricing": PRICING_LABELS,
        "packages": PACKAGES,
        "channels": CHANNEL_READY,
    }}


@router.get("/transactions")
async def transactions(
    page: int = 1, page_size: int = Query(default=20, le=100),
    current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """消费/入账流水（分页）"""
    uid = current_user["user_id"]
    q = select(CreditTransaction).where(CreditTransaction.user_id == uid) \
        .order_by(CreditTransaction.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()
    total = (await db.execute(
        select(func.count(CreditTransaction.id)).where(CreditTransaction.user_id == uid)
    )).scalar() or 0
    return {"code": 0, "data": [
        {"id": t.id, "amount": t.amount, "type": t.type, "ref": t.ref, "note": t.note,
         "balance_after": t.balance_after,
         "created_at": t.created_at.isoformat() if t.created_at else None}
        for t in rows
    ], "total": total}


class OrderCreate(BaseModel):
    package_id: str | None = None      # 选档位
    amount_fen: int | None = Field(default=None, ge=100)  # 或对公自定义金额（分），最低 ¥1
    channel: str


@router.post("/orders")
async def create_order(
    req: OrderCreate,
    current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """创建充值订单"""
    if req.channel not in CHANNELS:
        raise HTTPException(status_code=400, detail="无效支付渠道")
    if not CHANNEL_READY[req.channel]:
        raise HTTPException(status_code=400, detail="该支付渠道接入中（商户号申请中），请先使用对公转账或兑换码")

    if req.package_id:
        pkg = next((p for p in PACKAGES if p["id"] == req.package_id), None)
        if not pkg:
            raise HTTPException(status_code=400, detail="无效充值档位")
        amount_fen, credits = pkg["amount_fen"], pkg["credits"]
    elif req.amount_fen:
        if req.channel != "corporate":
            raise HTTPException(status_code=400, detail="自定义金额仅支持对公转账")
        amount_fen = req.amount_fen
        credits = amount_fen + round(amount_fen * 0.05)  # 1分=1 Credit + 5% 加赠
    else:
        raise HTTPException(status_code=400, detail="请选择充值档位或填写金额")

    order_no = "DB" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + secrets.token_hex(3).upper()
    order = CreditOrder(
        order_no=order_no, user_id=current_user["user_id"],
        amount_fen=amount_fen, credits=credits, channel=req.channel,
    )
    db.add(order)
    await db.flush()

    data = {"order_no": order_no, "amount_fen": amount_fen, "credits": credits,
            "channel": req.channel, "status": order.status}
    if req.channel == "corporate":
        data["corporate_account"] = CORPORATE_ACCOUNT
    return {"code": 0, "data": data}


class ProofSubmit(BaseModel):
    proof: str = Field(..., min_length=2, max_length=2000)


@router.post("/orders/{order_no}/proof")
async def submit_proof(
    order_no: str, req: ProofSubmit,
    current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """提交对公转账凭证（转账时间/金额/户名/流水号等）"""
    r = await db.execute(select(CreditOrder).where(
        CreditOrder.order_no == order_no, CreditOrder.user_id == current_user["user_id"]))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending":
        raise HTTPException(status_code=400, detail="订单状态不允许提交凭证")
    order.proof = req.proof
    await db.flush()
    return {"code": 0, "message": "凭证已提交，管理员核销后 Credits 自动到账"}


@router.get("/orders")
async def my_orders(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """我的充值订单"""
    r = await db.execute(select(CreditOrder).where(CreditOrder.user_id == current_user["user_id"])
                         .order_by(CreditOrder.created_at.desc()).limit(50))
    return {"code": 0, "data": [
        {"order_no": o.order_no, "amount_fen": o.amount_fen, "credits": o.credits,
         "channel": o.channel, "status": o.status, "proof": bool(o.proof),
         "created_at": o.created_at.isoformat() if o.created_at else None}
        for o in r.scalars().all()
    ]}


class RedeemSubmit(BaseModel):
    code: str = Field(..., min_length=4, max_length=32)


@router.post("/redeem")
async def redeem(
    req: RedeemSubmit,
    current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """兑换码兑换 Credits"""
    r = await db.execute(select(RedeemCode).where(RedeemCode.code == req.code.strip().upper()))
    rc = r.scalar_one_or_none()
    if not rc or rc.used:
        raise HTTPException(status_code=400, detail="兑换码无效或已被使用")
    rc.used = True
    rc.used_by = current_user["user_id"]
    rc.used_at = datetime.now(timezone.utc)
    tx = await add_transaction(db, current_user["user_id"], rc.credits, "redeem", ref=f"code:{rc.code}")
    return {"code": 0, "message": f"兑换成功，+{rc.credits} Credits", "data": {"balance": tx.balance_after}}


# ==================== 管理端 ====================

@router.get("/admin/orders")
async def admin_orders(
    status: str | None = None, page: int = 1, page_size: int = 20,
    current_user: dict = Depends(require_role(Roles.ADMIN)), db: AsyncSession = Depends(get_db),
):
    """订单列表（含用户邮箱），status 可筛 pending"""
    q = select(CreditOrder, User.email).outerjoin(User, CreditOrder.user_id == User.id)
    cq = select(func.count(CreditOrder.id))
    if status:
        q = q.where(CreditOrder.status == status)
        cq = cq.where(CreditOrder.status == status)
    q = q.order_by(CreditOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).all()
    total = (await db.execute(cq)).scalar() or 0
    return {"code": 0, "data": [
        {"order_no": o.order_no, "user_id": o.user_id, "email": email or "—",
         "amount_fen": o.amount_fen, "credits": o.credits, "channel": o.channel,
         "status": o.status, "proof": o.proof,
         "created_at": o.created_at.isoformat() if o.created_at else None}
        for o, email in rows
    ], "total": total}


@router.post("/admin/orders/{order_no}/confirm")
async def admin_confirm_order(
    order_no: str,
    current_user: dict = Depends(require_role(Roles.ADMIN)), db: AsyncSession = Depends(get_db),
):
    """核销订单：标记已支付并发放 Credits（幂等）"""
    r = await db.execute(select(CreditOrder).where(CreditOrder.order_no == order_no))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == "delivered":
        return {"code": 0, "message": "订单已核销过，无需重复操作"}
    if order.status != "pending":
        raise HTTPException(status_code=400, detail=f"订单状态为 {order.status}，不可核销")
    order.status = "delivered"
    order.paid_at = datetime.now(timezone.utc)
    order.handled_by = current_user["user_id"]
    await add_transaction(db, order.user_id, order.credits, "recharge", ref=f"order:{order.order_no}")
    return {"code": 0, "message": f"已核销，用户到账 {order.credits} Credits"}


@router.post("/admin/orders/{order_no}/cancel")
async def admin_cancel_order(
    order_no: str,
    current_user: dict = Depends(require_role(Roles.ADMIN)), db: AsyncSession = Depends(get_db),
):
    """取消未支付订单"""
    r = await db.execute(select(CreditOrder).where(CreditOrder.order_no == order_no))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending":
        raise HTTPException(status_code=400, detail="仅可取消待支付订单")
    order.status = "cancelled"
    return {"code": 0, "message": "订单已取消"}


class AdjustRequest(BaseModel):
    user_id: int
    amount: int  # 正加负减
    reason: str = Field(..., min_length=1, max_length=200)


@router.post("/admin/adjust")
async def admin_adjust(
    req: AdjustRequest,
    current_user: dict = Depends(require_role(Roles.ADMIN)), db: AsyncSession = Depends(get_db),
):
    """手动调整用户 Credits"""
    r = await db.execute(select(User).where(User.id == req.user_id))
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="用户不存在")
    tx = await add_transaction(
        db, req.user_id, req.amount, "adjust",
        ref=f"admin:{current_user['user_id']}", note=req.reason,
    )
    return {"code": 0, "message": "已调整", "data": {"balance": tx.balance_after}}


class CodeGenRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    credits: int = Field(..., ge=1, le=100000)


@router.post("/admin/redeem-codes")
async def admin_gen_codes(
    req: CodeGenRequest,
    current_user: dict = Depends(require_role(Roles.ADMIN)), db: AsyncSession = Depends(get_db),
):
    """批量生成兑换码"""
    alphabet = string.ascii_uppercase + string.digits
    codes = []
    for _ in range(req.count):
        code = "DB" + "".join(secrets.choice(alphabet) for _ in range(10))
        db.add(RedeemCode(code=code, credits=req.credits))
        codes.append(code)
    await db.flush()
    return {"code": 0, "data": {"codes": codes, "credits": req.credits}}


@router.get("/admin/summary")
async def admin_summary(
    current_user: dict = Depends(require_role(Roles.ADMIN)), db: AsyncSession = Depends(get_db),
):
    """Credits 总账：发放/消耗/充值收入"""
    async def _sum(*where):
        r = await db.execute(select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(*where))
        return int(r.scalar() or 0)

    gifted = await _sum(CreditTransaction.type == "gift")
    consumed = -await _sum(CreditTransaction.type == "consume")
    recharged = await _sum(CreditTransaction.type == "recharge")
    redeemed = await _sum(CreditTransaction.type == "redeem")

    r = await db.execute(select(func.coalesce(func.sum(CreditOrder.amount_fen), 0))
                         .where(CreditOrder.status == "delivered"))
    revenue_fen = int(r.scalar() or 0)
    r = await db.execute(select(func.count(CreditOrder.id)).where(CreditOrder.status == "pending"))
    pending_orders = int(r.scalar() or 0)

    return {"code": 0, "data": {
        "gifted": gifted, "consumed": consumed,
        "recharged": recharged, "redeemed": redeemed,
        "revenue_fen": revenue_fen, "pending_orders": pending_orders,
    }}
