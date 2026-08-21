"""语音识别 API — 音频转文字（ASR）

使用硅基流动（SiliconFlow）SenseVoice 模型实现语音转文字。
前端录音后上传音频文件，本接口调用 ASR 返回识别文本。
"""
import os
import uuid
import httpx
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.core.security import get_current_user

router = APIRouter(prefix="/api/v1/audio", tags=["语音识别"])

# 配置
AUDIO_DIR = os.environ.get("AUDIO_DIR", "/data/deepbreath/uploads/audio")
MAX_SIZE_MB = int(os.environ.get("MAX_AUDIO_SIZE_MB", "20"))
ALLOWED_AUDIO_EXT = {"mp3", "wav", "m4a", "ogg", "webm", "aac", "flac", "amr"}

# 硅基流动 ASR
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
SILICONFLOW_ASR_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
ASR_MODEL = os.environ.get("ASR_MODEL", "FunAudioLLM/SenseVoiceSmall")


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上传音频 → 语音转文字，返回识别文本"""
    # 校验格式
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in ALLOWED_AUDIO_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的音频格式：{ext}。支持：{', '.join(sorted(ALLOWED_AUDIO_EXT))}")

    # 读取内容并校验大小
    contents = await file.read()
    if len(contents) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"音频大小超过 {MAX_SIZE_MB}MB 限制")
    if len(contents) < 100:
        raise HTTPException(status_code=400, detail="音频文件无效或为空")

    if not SILICONFLOW_API_KEY:
        raise HTTPException(status_code=500, detail="ASR 服务未配置（缺少 SILICONFLOW_API_KEY）")

    # 保存音频（便于排查）
    filename = f"{uuid.uuid4().hex}.{ext}"
    save_dir = Path(AUDIO_DIR)
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename
    save_path.write_bytes(contents)

    # 调用硅基流动 SenseVoice
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            with open(save_path, "rb") as f:
                resp = await client.post(
                    SILICONFLOW_ASR_URL,
                    headers={"Authorization": f"Bearer {SILICONFLOW_API_KEY}"},
                    files={"file": (filename, f, f"audio/{ext}")},
                    data={"model": ASR_MODEL, "language": "zh"},
                )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"语音识别服务错误：{resp.status_code} {resp.text[:200]}")
        data = resp.json()
        text = (data.get("text") or "").strip()
        if not text:
            return {"code": 0, "data": {"text": "", "message": "未识别到语音内容"}}
        return {"code": 0, "data": {"text": text}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"语音识别失败：{str(e)[:200]}")
