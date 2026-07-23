"""发送 APK 安装包到指定邮箱（读取 backend/.env 的 SMTP 配置）

用法: python3 send_apk.py <apk路径> <收件邮箱>
"""
import smtplib
import sys
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

ENV_PATH = "/root/deep-breath/backend/.env"


def load_env(path):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def main():
    apk_path, to_addr = sys.argv[1], sys.argv[2]
    apk_name = os.path.basename(apk_path)
    env = load_env(ENV_PATH)
    host = env.get("SMTP_HOST", "smtp.qq.com")
    port = int(env.get("SMTP_PORT", "465"))
    user = env.get("SMTP_USER")
    password = env.get("SMTP_PASSWORD") or env.get("QQMAIL_PASSWORD")

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = f"🍃 DeepBreath 安卓 APP 安装包 {apk_name}"

    size_mb = os.path.getsize(apk_path) / 1024 / 1024
    html = f"""<html><body style="font-family:sans-serif;color:#3d3d3d;max-width:600px;margin:0 auto;padding:20px">
<div style="text-align:center;padding:20px 0">
<div style="font-size:36px">🍃</div>
<h2 style="color:#7c8a7a">DeepBreath 安卓 APP</h2>
</div>
<div style="background:#f8f6f3;border-radius:12px;padding:20px;line-height:1.8">
<p><b>安装步骤：</b></p>
<ol>
<li>在安卓手机上打开本邮件，下载附件 <b>{apk_name}</b>（{size_mb:.1f} MB）</li>
<li>点击下载的文件安装；若提示「禁止安装未知来源应用」，在弹出的设置里允许本次安装</li>
<li>已安装旧版的话可直接覆盖升级，数据不受影响</li>
</ol>
<p style="color:#888;font-size:13px">说明：APP 采用联网壳模式，内容与网页版实时同步——以后功能更新无需重新安装。iPhone 用户请用 Safari 打开 https://luoyuyu.cn/app/ 后「分享 → 添加到主屏幕」。</p>
</div>
<p style="color:#aaa;font-size:12px;margin-top:20px;text-align:center">—— DeepBreath 深呼吸 · 你的心理陪伴者</p>
</body></html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))

    with open(apk_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=apk_name)
    part["Content-Disposition"] = f'attachment; filename="{apk_name}"'
    msg.attach(part)

    with smtplib.SMTP_SSL(host, port) as server:
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())
    print(f"已发送 {apk_path} ({size_mb:.1f}MB) → {to_addr}")


if __name__ == "__main__":
    main()
