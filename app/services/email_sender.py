"""心理学智能体 — 邮件发送模块"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from email import encoders

SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
FROM_EMAIL = "505055601@qq.com"
FROM_NAME = "心理学智能体"
SMTP_PASSWORD = os.environ.get("QQMAIL_PASSWORD", "")


def send_report(to_email: str, pdf_bytes: bytes, filename: str) -> tuple[bool, str]:
    """发送 PDF 报告到指定邮箱（也用于发送 HTML 内容）"""
    if not SMTP_PASSWORD:
        return False, "SMTP 密码未配置"

    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((FROM_NAME, FROM_EMAIL))
    msg["To"] = to_email
    msg["Subject"] = "🧠 心理学对话报告"
    msg["Date"] = formatdate(localtime=True)

    # HTML 正文
    html = f"""\
<html>
<body style="font-family: sans-serif; color: #3d3d3d; max-width: 600px; margin: 0 auto; padding: 20px;">
<div style="text-align: center; padding: 30px 0;">
<div style="font-size: 48px; margin-bottom: 12px;">🧠</div>
<h2 style="color: #7c8a7a; margin: 0;">心理学对话报告</h2>
</div>
<p>你好！</p>
<p>这是你的心理学对话报告，附件中是完整的 PDF 文件。</p>
<p style="color: #8a8a8a; font-size: 12px; line-height: 1.6; padding: 12px; background: #f5f0eb; border-radius: 8px;">
📌 本报告由 AI 辅助生成，仅供参考，不替代专业心理咨询。
</p>
<p style="margin-top: 24px; color: #8a8a8a; font-size: 12px;">
—— 心理学智能体
</p>
</body>
</html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))

    # 附件
    part = MIMEBase("application", "octet-stream")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f"attachment; filename=\"{filename}\"",
    )
    msg.attach(part)

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.login(FROM_EMAIL, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def send_html_email(to_email: str, subject: str, html_body: str) -> tuple[bool, str]:
    """发送 HTML 邮件正文"""
    if not SMTP_PASSWORD:
        return False, "SMTP 密码未配置"

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((FROM_NAME, FROM_EMAIL))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.login(FROM_EMAIL, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def send_email_with_audio(to_email, subject, html_body, audio_bytes=None):
    if not SMTP_PASSWORD:
        return False, "SMTP password not configured"
    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((FROM_NAME, FROM_EMAIL))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    if audio_bytes and len(audio_bytes) > 100:
        part = MIMEBase("audio", "mpeg")
        part.set_payload(audio_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", 'attachment; filename="voice.mp3"')
        msg.attach(part)
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.login(FROM_EMAIL, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)
