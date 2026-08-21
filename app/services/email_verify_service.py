"""邮箱验证码服务 — 通过邮件发送验证码并校验（与短信验证码机制对齐）

复用 Redis 存储验证码，复用 email_sender 发送 HTML 邮件。
配置（.env）：
  QQMAIL_PASSWORD  发信邮箱 SMTP 授权码（email_sender 已用；未配置时 MOCK 模式放行校验）
"""
import logging
import os
import secrets

from app.core.redis import redis_client, check_rate_limit
from app.services.email_sender import send_html_email

logger = logging.getLogger("email_verify")

# 发信能力：QQ 邮箱授权码配置后即为真实发送；未配置为 MOCK（校验放行，便于开发联调）
EMAIL_ENABLED = bool(os.environ.get("QQMAIL_PASSWORD", ""))

CODE_TTL = 300        # 验证码有效期 5 分钟
RESEND_WINDOW = 60    # 同邮箱 60 秒一条
DAILY_LIMIT = 10      # 同邮箱每日上限

EMAIL_CODE_RE = r"^[0-9]{6}$"


def valid_email(email: str) -> bool:
    email = (email or "").strip().lower()
    return "@" in email and "." in email and len(email) <= 255


async def send_email_code(email: str, ip: str = "") -> tuple[bool, str]:
    """生成并发送邮箱验证码。限流/失败返回 (False, 原因)"""
    email = (email or "").strip().lower()
    if not valid_email(email):
        return False, "邮箱格式不正确"

    if not await check_rate_limit(f"email:rl:{email}", 1, RESEND_WINDOW):
        return False, "发送太频繁，请 60 秒后再试"
    if not await check_rate_limit(f"email:daily:{email}", DAILY_LIMIT, 86400):
        return False, "该邮箱今日验证码次数已达上限"
    if ip and not await check_rate_limit(f"email:ip:{ip}", 20, 86400):
        return False, "请求过于频繁，请明天再试"

    code = f"{secrets.randbelow(1000000):06d}"
    await redis_client.set(f"email:code:{email}", code, ex=CODE_TTL)

    if not EMAIL_ENABLED:
        logger.warning("[EMAIL-MOCK] email=%s code=%s (QQMAIL_PASSWORD 未配置，校验放行)", email, code)
        return True, ""

    # 真实发送 HTML 邮件
    subject = "🔐 您的验证码"
    html = f"""\
<html>
<body style="font-family: sans-serif; color: #3d3d3d; max-width: 600px; margin: 0 auto; padding: 20px;">
<div style="text-align: center; padding: 30px 0;">
<div style="font-size: 48px; margin-bottom: 12px;">🔐</div>
<h2 style="color: #7c8a7a; margin: 0;">验证码</h2>
</div>
<p>你好！</p>
<p>你正在使用邮箱验证，本次验证码为：</p>
<div style="text-align: center; margin: 24px 0;">
<span style="display: inline-block; font-size: 32px; font-weight: bold; letter-spacing: 8px;
     color: #4a6a4a; background: #f5f0eb; padding: 12px 28px; border-radius: 8px;">{code}</span>
</div>
<p style="color: #8a8a8a; font-size: 13px;">验证码 5 分钟内有效，请勿泄露给他人。</p>
<p style="margin-top: 24px; color: #8a8a8a; font-size: 12px;">—— 心理学智能体</p>
</body>
</html>"""
    ok, err = send_html_email(email, subject, html)
    if not ok:
        logger.error("[EMAIL-SEND-FAIL] email=%s err=%s", email, err)
        return False, f"邮件发送失败：{err}"
    logger.info("[EMAIL-SENT] email=%s", email)
    return True, ""


async def verify_email_code(email: str, code: str) -> bool:
    """校验邮箱验证码（一次性）。MOCK 模式放行"""
    if not EMAIL_ENABLED:
        return True
    email = (email or "").strip().lower()
    stored = await redis_client.get(f"email:code:{email}")
    if stored and code and stored == code.strip():
        await redis_client.delete(f"email:code:{email}")
        return True
    return False
