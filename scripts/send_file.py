"""通用邮件发送：send_file.py <文件路径> <收件邮箱> [邮件主题]"""
import smtplib, sys, os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

file_path, to_addr = sys.argv[1], sys.argv[2]
subject = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(file_path)

env = {}
for line in open('/root/deep-breath/backend/.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        env[k.strip()] = v.strip()

user = env['SMTP_USER']
pwd = env.get('SMTP_PASSWORD') or env.get('QQMAIL_PASSWORD')

msg = MIMEMultipart()
msg['From'] = user
msg['To'] = to_addr
msg['Subject'] = subject

msg.attach(MIMEText(
    '<html><body style="font-family:sans-serif"><h2>' + subject + '</h2>'
    '<p>见附件。</p>'
    '<p style="color:#aaa;font-size:12px">DeepBreath</p></body></html>',
    'html', 'utf-8'))

with open(file_path, 'rb') as f:
    part = MIMEApplication(f.read(), Name=os.path.basename(file_path))
part['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
msg.attach(part)

with smtplib.SMTP_SSL(env.get('SMTP_HOST', 'smtp.qq.com'), int(env.get('SMTP_PORT', '465'))) as s:
    s.login(user, pwd)
    s.sendmail(user, [to_addr], msg.as_string())
print(f'SENT {os.path.getsize(file_path)} bytes -> {to_addr}')
