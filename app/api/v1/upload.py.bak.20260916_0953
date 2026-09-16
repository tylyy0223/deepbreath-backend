"""文件上传 API — 图片上传（自动压缩，节省服务器空间）"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pathlib import Path
import uuid
import os
import io

router = APIRouter(prefix="/api/v1/upload", tags=["文件上传"])

# 上传配置
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/deepbreath/uploads")
MAX_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "10"))
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif"}

# 压缩配置
MAX_DIMENSION = int(os.environ.get("IMAGE_MAX_DIMENSION", "2048"))  # 最长边像素
JPEG_QUALITY = int(os.environ.get("IMAGE_JPEG_QUALITY", "82"))      # JPEG/WebP 质量
MAX_PNG_BYTES = 600 * 1024  # PNG 超过此大小尝试转 WebP（保留透明，体积小 5-10 倍）

try:
    from PIL import Image
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False


def _compress_image(contents: bytes, ext: str) -> tuple[bytes, str]:
    """压缩图片：缩放 + 质量压缩。

    返回 (压缩后的字节, 目标扩展名)。若压缩无效则返回原字节 + 原扩展名。
    HEIC/HEIF 例外：无论压缩是否更小都必须转 JPEG（浏览器不支持 HEIC）。
    """
    if not _PIL_AVAILABLE:
        return contents, ext
    try:
        img = Image.open(io.BytesIO(contents))
        fmt = img.format.upper() if img.format else ext.upper()
    except Exception:
        return contents, ext

    # GIF 动图：保留动画，不压缩
    if fmt == "GIF":
        return contents, "gif"

    has_alpha = "A" in img.getbands() or (img.mode == "P" and "transparency" in img.info)

    # 缩放：最长边 > MAX_DIMENSION 时等比缩小
    if max(img.size) > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    out = io.BytesIO()

    if fmt in ("JPEG", "JPG"):
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        target_fmt = "jpg"
    elif fmt == "WEBP":
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if has_alpha else "RGB")
        img.save(out, format="WEBP", quality=JPEG_QUALITY, method=6)
        target_fmt = "webp"
    elif fmt == "PNG":
        # 大 PNG 转 WebP（保留透明，体积小很多）；小 PNG 保持原格式 optimize
        if len(contents) > MAX_PNG_BYTES or max(img.size) > 1600:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if has_alpha else "RGB")
            img.save(out, format="WEBP", quality=min(JPEG_QUALITY + 3, 90), method=6)
            target_fmt = "webp"
        else:
            if img.mode not in ("RGB", "RGBA", "P"):
                img = img.convert("RGBA" if has_alpha else "RGB")
            img.save(out, format="PNG", optimize=True)
            target_fmt = "png"
    elif fmt in ("HEIC", "HEIF"):
        # HEIC/HEIF 强制转 JPEG（Web 兼容；浏览器不支持 HEIC，必须转换）
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        return out.getvalue(), "jpg"  # 强制转换，不检查"压缩后更大"
    else:
        # 其他格式原样保存
        return contents, ext

    result = out.getvalue()
    # 压缩后反而更大（如已压缩过的图）→ 保留原图
    if len(result) >= len(contents):
        return contents, ext
    return result, target_fmt


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    """上传单张图片（自动压缩），返回可访问的图片 URL"""
    # 校验扩展名
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式：{ext}。支持：{', '.join(sorted(ALLOWED_EXTENSIONS))}")

    # 读取内容并校验大小
    contents = await file.read()
    if len(contents) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件大小超过 {MAX_SIZE_MB}MB 限制")

    # 自动压缩
    compressed, final_ext = _compress_image(contents, ext)

    # 生成唯一文件名
    filename = f"{uuid.uuid4().hex}.{final_ext}"
    save_dir = Path(UPLOAD_DIR)
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename
    save_path.write_bytes(compressed)

    original_size = len(contents)
    final_size = len(compressed)
    saved = original_size - final_size

    # 返回可访问 URL（通过 nginx 静态文件路径）
    url = f"/uploads/{filename}"
    return {
        "code": 0,
        "data": {
            "url": url,
            "filename": filename,
            "original_size": original_size,
            "final_size": final_size,
            "saved_bytes": max(saved, 0),
            "compressed": saved > 0,
        },
    }
