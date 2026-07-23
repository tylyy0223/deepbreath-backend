"""TTS 语音合成 API — MiniMax + 音频持久化/内容绑定"""
import hashlib, os, httpx, json
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from datetime import datetime, timezone
from app.core.database import async_session
from app.core.security import get_current_user
from app.services.credits_service import PRICING, get_balance, charge
from app.models.cache import UserAudioCache

try:
    from app.models.cache import TtsBinding
except ImportError:
    class TtsBinding:  # type: ignore[no-redef]
        """模型尚未部署时的占位，避免 import 致命错误"""


router = APIRouter(prefix="/api/v1/tts", tags=["TTS"])

# 持久化目录（/tmp 重启即失，音频要长期与内容绑定）
CACHE_DIR = "/var/lib/deepbreath/tts"
os.makedirs(CACHE_DIR, exist_ok=True)

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_TTS_URL = "https://api.minimaxi.com/v1/t2a_v2"
VOICE_ID = "female-shaonv"
VOICE_OPTIONS = {
    "female": "female-shaonv",
    "male": "male-qn-qingse",
}


def text_hash(text: str, voice_id: str = "") -> str:
    return hashlib.md5((text + (voice_id or VOICE_ID)).encode()).hexdigest()


def audio_path(h: str) -> str:
    return os.path.join(CACHE_DIR, f"mm_{h}.mp3")


def audio_exists(h: str) -> bool:
    p = audio_path(h)
    return os.path.exists(p) and os.path.getsize(p) > 100


async def _record(user_id: int, h: str, text: str, ref: str | None, size: int):
    """记录音频（UserAudioCache）与内容绑定（TtsBinding），幂等"""
    db = async_session()
    try:
        r = await db.execute(select(UserAudioCache).where(
            UserAudioCache.user_id == user_id, UserAudioCache.text_hash == h))
        row = r.scalars().first()
        if row:
            row.play_count += 1
            row.last_played_at = datetime.now(timezone.utc)
        else:
            db.add(UserAudioCache(user_id=user_id, text_hash=h, text=text[:2000],
                                  file_path=audio_path(h), file_size=size))
        if ref:
            r2 = await db.execute(select(TtsBinding).where(TtsBinding.ref == ref))
            b = r2.scalars().first()
            if b:
                b.text_hash = h
            else:
                db.add(TtsBinding(ref=ref, text_hash=h))
        await db.commit()
    except Exception:
        await db.rollback()
    finally:
        await db.close()


async def _call_minimax(text: str, voice_id: str) -> bytes:
    """调用 MiniMax API 生成音频并保存到磁盘（不涉及用户、不计费）"""
    h = text_hash(text, voice_id)
    cache_path = audio_path(h)
    if audio_exists(h):
        with open(cache_path, "rb") as f:
            return f.read()

    if not MINIMAX_API_KEY:
        raise Exception("TTS 未配置")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            MINIMAX_TTS_URL,
            headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "speech-01-turbo",
                "text": text,
                "stream": False,
                "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
                "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
            },
        )
        data = resp.json()
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") != 0:
            raise Exception(str(base_resp))

        audio_hex = data.get("data", {}).get("audio", "") or data.get("extra_info", {}).get("audio", "")
        if not audio_hex:
            raise Exception(f"Unrecognized response: {json.dumps(data, ensure_ascii=False)[:300]}")
        audio_bytes = bytes.fromhex(audio_hex)
        if len(audio_bytes) < 100:
            raise Exception(f"Audio too small: {len(audio_bytes)} bytes")

        with open(cache_path, "wb") as f:
            f.write(audio_bytes)
        return audio_bytes


async def pre_generate_tts(text: str, ref: str, user_id: int):
    """预生成 TTS 音频（所有音色），静默运行，不计费。
    用于书介绍等内容的音频预缓存，后续用户点击播放时秒播。"""
    text = text.strip()
    if not text or len(text) > 3000:
        return
    # 对所有音色预生成
    for voice_id in set(VOICE_OPTIONS.values()):
        try:
            h = text_hash(text, voice_id)
            if audio_exists(h):
                continue  # 已有缓存，跳过
            audio_bytes = await _call_minimax(text, voice_id)
            await _record(user_id, h, text, ref, len(audio_bytes))
        except Exception:
            pass  # 预生成失败不影响主流程


class TTSRequest(BaseModel):
    text: str
    ref: str | None = None  # 内容绑定标识：article:<slug> / post:<id> 等
    voice_id: str = ""  # 语音音色：female / male，默认使用系统默认（女声）


@router.post("/synthesize")
async def synthesize(req: TTSRequest, current_user: dict = Depends(get_current_user)):
    voice_id = VOICE_OPTIONS.get(req.voice_id, VOICE_ID)
    text = req.text.strip()
    if not text or len(text) > 3000:
        raise HTTPException(status_code=400, detail="文本为空或过长")
    if not MINIMAX_API_KEY:
        raise HTTPException(status_code=500, detail="TTS 未配置")

    h = text_hash(text, voice_id)
    cache_path = audio_path(h)

    # 缓存命中：免费播放，仍补记绑定
    if audio_exists(h):
        with open(cache_path, "rb") as f:
            data = f.read()
        await _record(current_user["user_id"], h, text, req.ref, len(data))
        return Response(content=data, media_type="audio/mpeg", headers={"X-Cache": "HIT"})

    # 缓存未命中：需要调用 MiniMax，先检查余额
    cost = PRICING["tts"]
    db = async_session()
    try:
        if await get_balance(db, current_user["user_id"]) < cost:
            raise HTTPException(status_code=402, detail=f"Credits 余额不足（语音朗读需 {cost} Credits），请充值后再试")
    finally:
        await db.close()

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                MINIMAX_TTS_URL,
                headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "speech-01-turbo",
                    "text": text,
                    "stream": False,
                    "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
                    "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
                },
            )
            data = resp.json()
            base_resp = data.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                raise Exception(str(base_resp))

            audio_hex = data.get("data", {}).get("audio", "") or data.get("extra_info", {}).get("audio", "")
            if not audio_hex:
                raise Exception(f"Unrecognized response: {json.dumps(data, ensure_ascii=False)[:300]}")
            audio_bytes = bytes.fromhex(audio_hex)
            if len(audio_bytes) < 100:
                raise Exception(f"Audio too small: {len(audio_bytes)} bytes")

            with open(cache_path, "wb") as f:
                f.write(audio_bytes)

            # 合成成功后扣费 + 记录绑定
            db = async_session()
            try:
                await charge(db, current_user["user_id"], cost, ref="tts", note="语音朗读")
                await db.commit()
            except Exception:
                await db.rollback()
            finally:
                await db.close()
            await _record(current_user["user_id"], h, text, req.ref, len(audio_bytes))

            return Response(content=audio_bytes, media_type="audio/mpeg", headers={"X-Cache": "MISS"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 失败: {str(e)}")


class ExistsRequest(BaseModel):
    texts: dict[str, str] = Field(..., description="{key: 文本} 批量检查是否已有音频")


@router.post("/exists")
async def exists(req: ExistsRequest, current_user: dict = Depends(get_current_user)):
    """批量检查文本是否已生成音频（按内容哈希，任意音色命中即算）"""
    if len(req.texts) > 200:
        raise HTTPException(status_code=400, detail="单次最多检查 200 条")
    # 检查所有音色，任意一个命中就算有音频
    all_voice_ids = list(VOICE_OPTIONS.values()) + [VOICE_ID]
    keys = [k for k, t in req.texts.items() if t and any(
        audio_exists(text_hash(t.strip(), vid)) for vid in all_voice_ids
    )]
    return {"code": 0, "data": {"keys": keys}}


class BoundRequest(BaseModel):
    refs: list[str] = Field(..., max_length=200)


@router.post("/bound")
async def bound(req: BoundRequest, current_user: dict = Depends(get_current_user)):
    """批量检查内容标识是否绑定了音频（文章卡片小图标用）"""
    if not req.refs:
        return {"code": 0, "data": {"refs": []}}
    db = async_session()
    try:
        r = await db.execute(select(TtsBinding).where(TtsBinding.ref.in_(req.refs)))
        rows = r.scalars().all()
    finally:
        await db.close()
    have = [b.ref for b in rows if audio_exists(b.text_hash)]
    return {"code": 0, "data": {"refs": have}}
