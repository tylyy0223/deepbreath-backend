"""邮件发送 API"""
import html
import re
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from app.core.database import async_session
from app.core.security import get_current_user
from app.services.email_sender import send_html_email
from app.services.credits_service import PRICING, get_balance, charge

router = APIRouter(prefix="/api/v1/email", tags=["邮件"])


class EmailRequest(BaseModel):
    email: str
    subject: str = "🧠 心理学智能体回复"
    content: str


@router.post("/send")
async def send_email(req: EmailRequest, current_user: dict = Depends(get_current_user)):
    """发送 AI 回复内容到邮箱"""
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="内容为空")

    # 邮箱格式校验
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', req.email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    # 频率限制：每用户每小时最多 10 封
    from app.core.redis import check_rate_limit
    if not await check_rate_limit(f"email:rl:{current_user['user_id']}", 10, 3600):
        raise HTTPException(status_code=429, detail="邮件发送过于频繁，请稍后再试")

    cost = PRICING["email"]
    db = async_session()
    try:
        if await get_balance(db, current_user["user_id"]) < cost:
            raise HTTPException(status_code=402, detail=f"Credits 余额不足（邮件发送需 {cost} Credits），请充值后再试")
    finally:
        await db.close()

    html = f"""<html>
<body style="font-family:sans-serif;color:#3d3d3d;max-width:600px;margin:0 auto;padding:20px">
<div style="text-align:center;padding:20px 0">
<div style="font-size:36px">🍃</div>
<h2 style="color:#7c8a7a">深呼吸 · AI 对话</h2>
</div>
<div style="background:#f8f6f3;border-radius:12px;padding:20px;line-height:1.8;white-space:pre-wrap">
{html.escape(req.content)}
</div>
<p style="color:#aaa;font-size:12px;margin-top:20px;text-align:center">
—— 深呼吸 DeepBreath · 你的心理陪伴者
</p>
</body></html>"""

    # 先扣费再发送（charge 内部有 advisory lock，保证原子性）
    db2 = async_session()
    try:
        charged = await charge(db2, current_user["user_id"], cost, ref="email", note=f"邮件发送至 {req.email}")
        await db2.commit()
        if not charged:
            raise HTTPException(status_code=402, detail="Credits 余额不足，请充值后再试")
    except HTTPException:
        raise
    except Exception:
        await db2.rollback()
        raise
    finally:
        await db2.close()

    ok, err = send_html_email(req.email, req.subject, html)
    if not ok:
        raise HTTPException(status_code=500, detail=f"发送失败: {err}")

    return {"code": 0, "message": "已发送"}
