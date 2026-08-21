"""短信验证码服务 — 腾讯云短信

配置（.env，systemd EnvironmentFile 加载）：
  TENCENT_SMS_SDKAPPID   短信应用 SDKAppID
  TENCENT_SMS_APPKEY     短信应用 App Key
  TENCENT_SMS_SIGN       已审核通过的签名内容（如：深呼吸）
  TENCENT_SMS_TPL_ID     已审核通过的模板 ID
  TENCENT_SMS_TPL_PARAMS 模板变量，逗号分隔，{code} 会替换为验证码（默认 "{code}"；
                         若模板为「验证码{1}，{2}分钟内有效」则配 "{code},5"）

四项核心配置齐全时自动启用真实发送；缺任何一项则为 MOCK 模式：
验证码写服务日志（journalctl -u deepbreath | grep SMS-MOCK）且校验放行。
"""
import hashlib
import logging
import os
import random as _random
import re
import secrets
import time

import httpx

from app.core.redis import redis_client, check_rate_limit

logger = logging.getLogger("sms")

TENCENT_SDKAPPID = os.environ.get("TENCENT_SMS_SDKAPPID", "")
TENCENT_APPKEY = os.environ.get("TENCENT_SMS_APPKEY", "")
TENCENT_SIGN = os.environ.get("TENCENT_SMS_SIGN", "")
TENCENT_TPL_ID = os.environ.get("TENCENT_SMS_TPL_ID", "")
TENCENT_TPL_PARAMS = os.environ.get("TENCENT_SMS_TPL_PARAMS", "{code}")

TENCENT_SMS_URL = "https://yun.tim.qq.com/v5/tlssmssvr/sendsms"

# 签名与模板审核通过并配置后自动启用真实发送
SMS_ENABLED = bool(TENCENT_SDKAPPID and TENCENT_APPKEY and TENCENT_SIGN and TENCENT_TPL_ID)

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

CODE_TTL = 300        # 验证码有效期 5 分钟
RESEND_WINDOW = 60    # 同号 60 秒一条
DAILY_LIMIT = 10      # 同号每日上限


def valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone or ""))


def mask_phone(phone: str | None) -> str | None:
    if not phone or len(phone) != 11:
        return phone
    return f"{phone[:3]}****{phone[7:]}"


async def send_code(phone: str, ip: str = "") -> None:
    """生成并发送验证码。限流触发抛 ValueError（调用方转 429）"""
    if not await check_rate_limit(f"sms:rl:{phone}", 1, RESEND_WINDOW):
        raise ValueError("发送太频繁，请 60 秒后再试")
    if not await check_rate_limit(f"sms:daily:{phone}", DAILY_LIMIT, 86400):
        raise ValueError("该手机号今日验证码次数已达上限")
    if ip and not await check_rate_limit(f"sms:ip:{ip}", 20, 86400):
        raise ValueError("请求过于频繁，请明天再试")

    code = f"{secrets.randbelow(1000000):06d}"
    await redis_client.set(f"sms:code:{phone}", code, ex=CODE_TTL)

    if SMS_ENABLED:
        await _send_via_tencent(phone, code)
    else:
        logger.warning("[SMS-MOCK] phone=%s code=%s (签名/模板未配置齐全，验证码校验放行)", phone, code)


async def verify_code(phone: str, code: str) -> bool:
    """校验验证码（一次性）。MOCK 模式放行"""
    if not SMS_ENABLED:
        return True
    stored = await redis_client.get(f"sms:code:{phone}")
    if stored and code and stored == code.strip():
        await redis_client.delete(f"sms:code:{phone}")
        return True
    return False


async def _send_via_tencent(phone: str, code: str) -> None:
    """腾讯云短信 v5 单发接口（SDKAppID + AppKey 签名）"""
    rand = str(_random.randint(100000, 999999))
    now = int(time.time())
    sig = hashlib.sha256(
        f"appkey={TENCENT_APPKEY}&random={rand}&time={now}&mobile={phone}".encode()
    ).hexdigest()
    params = [p.replace("{code}", code) for p in TENCENT_TPL_PARAMS.split(",")]

    body = {
        "ext": "",
        "extend": "",
        "params": params,
        "sig": sig,
        "sign": TENCENT_SIGN,
        "tel": {"mobile": phone, "nationcode": "86"},
        "time": now,
        "tpl_id": int(TENCENT_TPL_ID),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{TENCENT_SMS_URL}?sdkappid={TENCENT_SDKAPPID}&random={rand}",
            json=body,
        )
        data = resp.json()
    if data.get("result") != 0:
        logger.error("[SMS-FAIL] phone=%s result=%s errmsg=%s", phone, data.get("result"), data.get("errmsg"))
        raise ValueError(f"短信发送失败：{data.get('errmsg', '未知错误')}")
    logger.info("[SMS-SENT] phone=%s sid=%s", mask_phone(phone), data.get("sid", ""))
