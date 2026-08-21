"""TTS 语音合成 API — MiniMax + 用户个性化缓存"""
import hashlib, os, httpx, json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select, update, func
from pydantic import BaseModel

from app.core.database import async_session
from app.core.security import get_current_user, get_optional_user
from app.models.cache import UserAudioCache

router = APIRouter(prefix="/api/v1/tts", tags=["TTS"])

CACHE_DIR = "/tmp/deepbreath_tts"
os.makedirs(CACHE_DIR, exist_ok=True)

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_TTS_URL = "https://api.minimaxi.com/v1/t2a_v2"
VOICE_ID = "female-shaonv"


class TTSRequest(BaseModel):
    text: str


@router.post("/synthesize")
async def synthesize(
    req: TTSRequest,
    current_user: dict = Depends(get_optional_user),
):
    """文本转语音 — 全局文件缓存 + 用户级记录"""
    text = req.text.strip()
    if not text or len(text) > 3000:
        raise HTTPException(status_code=400, detail="文本为空或过长")
    if not MINIMAX_API_KEY:
        raise HTTPException(status_code=500, detail="TTS 未配置")

    user_id = current_user["user_id"] if current_user else None
    text_hash = hashlib.md5((text + VOICE_ID).encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"mm_{text_hash}.mp3")
    from_cache = os.path.exists(cache_path) and os.path.getsize(cache_path) > 100

    if not from_cache:
        # 调用 MiniMax 生成
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    MINIMAX_TTS_URL,
                    headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": "speech-01-turbo", "text": text, "stream": False,
                        "voice_setting": {"voice_id": VOICE_ID, "speed": 1.0, "vol": 1.0, "pitch": 0},
                        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
                    },
                )
                data = resp.json()
                base_resp = data.get("base_resp", {})
                if base_resp.get("status_code") != 0:
                    raise Exception(str(base_resp))
                audio_hex = data.get("data", {}).get("audio", "")
                if audio_hex:
                    audio_bytes = bytes.fromhex(audio_hex)
                else:
                    audio_hex = data.get("extra_info", {}).get("audio", "")
                    if audio_hex:
                        audio_bytes = bytes.fromhex(audio_hex)
                    else:
                        raise Exception(f"Unexpected response: {json.dumps(data, ensure_ascii=False)[:200]}")
                if len(audio_bytes) < 100:
                    raise Exception(f"Audio too small: {len(audio_bytes)} bytes")
                with open(cache_path, "wb") as f:
                    f.write(audio_bytes)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TTS 失败: {str(e)}")

    file_size = os.path.getsize(cache_path)

    # 记录用户音频缓存
    if user_id:
        db = async_session()
        try:
            r = await db.execute(
                select(UserAudioCache).where(
                    UserAudioCache.user_id == user_id,
                    UserAudioCache.text_hash == text_hash,
                )
            )
            existing = r.scalar_one_or_none()
            if existing:
                await db.execute(
                    update(UserAudioCache)
                    .where(UserAudioCache.id == existing.id)
                    .values(play_count=UserAudioCache.play_count + 1, last_played_at=datetime.now(timezone.utc))
                )
            else:
                db.add(UserAudioCache(
                    user_id=user_id, text_hash=text_hash, text=text[:500],
                    file_path=cache_path, file_size=file_size,
                ))
            await db.commit()
        except Exception:
            await db.rollback()
        finally:
            await db.close()

    with open(cache_path, "rb") as f:
        return Response(
            content=f.read(), media_type="audio/mpeg",
            headers={"X-Cache": "HIT" if from_cache else "MISS", "X-File-Size": str(file_size)},
        )


@router.get("/history")
async def audio_history(
    current_user: dict = Depends(get_current_user),
    page: int = Query(default=1, le=100),
    page_size: int = Query(default=20, le=100),
):
    """用户的语音生成历史"""
    db = async_session()
    try:
        r = await db.execute(
            select(UserAudioCache)
            .where(UserAudioCache.user_id == current_user["user_id"])
            .order_by(UserAudioCache.last_played_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = r.scalars().all()

        r2 = await db.execute(
            select(func.count(UserAudioCache.id))
            .where(UserAudioCache.user_id == current_user["user_id"])
        )
        total = r2.scalar()

        return {
            "code": 0,
            "data": [
                {
                    "id": a.id, "text": a.text, "play_count": a.play_count,
                    "file_size": a.file_size,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "last_played_at": a.last_played_at.isoformat() if a.last_played_at else None,
                }
                for a in items
            ],
            "total": total, "page": page, "page_size": page_size,
        }
    finally:
        await db.close()
