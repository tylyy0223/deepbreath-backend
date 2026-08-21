"""邮件发送 API"""
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
{req.content}
</div>
<p style="color:#aaa;font-size:12px;margin-top:20px;text-align:center">
—— 深呼吸 DeepBreath · 你的心理陪伴者
</p>
</body></html>"""

    ok, err = send_html_email(req.email, req.subject, html)
    if not ok:
        raise HTTPException(status_code=500, detail=f"发送失败: {err}")

    # 发送成功后扣费
    db = async_session()
    try:
        await charge(db, current_user["user_id"], cost, ref="email", note=f"邮件发送至 {req.email}")
        await db.commit()
    except Exception:
        await db.rollback()
    finally:
        await db.close()

    return {"code": 0, "message": "已发送"}
