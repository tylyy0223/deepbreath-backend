"""AI 听书讲解 - 章节列表 / 详情 / 进度 / 限流"""
import os
import re
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import psycopg2
import psycopg2.extras

from app.core.database import async_session
from app.core.security import get_current_user
from sqlalchemy import select, update

router = APIRouter(prefix="/api/v1/book-listen", tags=["AI听书"])

DB_KW = dict(
    host=os.environ.get("DEEPBREATH_DB_HOST") or os.environ.get("DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("DEEPBREATH_DB_PORT") or os.environ.get("DB_PORT", "5432")),
    dbname=os.environ.get("DEEPBREATH_DB_NAME") or os.environ.get("DB_NAME", "deepbreath"),
    user=os.environ.get("DEEPBREATH_DB_USER") or os.environ.get("DB_USER", "deepbreath"),
    password=os.environ.get("DEEPBREATH_DB_PASSWORD") or os.environ.get("DB_PASSWORD", ""),
)
DEFAULT_LIMIT_MIN = 120  # 默认 120min/天, 实际从 app_settings 读
AUDIO_LINK_SECRET = "deepbreath_audio_2026"  # 必须与 47.103.62.70 / 47.103.58.89 nginx /audio/ location 的 secure_link_md5 一致
AUDIO_LINK_TTL = 7200  # 2 小时有效


def make_secure_audio_url(audio_url: str, ttl: int = AUDIO_LINK_TTL) -> str:
    """生成 nginx secure_link 签名的 URL
    audio_url: '/audio/004-271/ch01.mp3'
    返回: '/audio/004-271/ch01.mp3?e=<expire>&st=<md5>'
    """
    if not audio_url or not audio_url.startswith("/audio/"):
        return audio_url
    import hashlib
    import time
    expires = int(time.time()) + ttl
    # nginx secure_link_md5: "$secure_link_expires$uri <secret>" (中间有空格)
    sig = hashlib.md5(f"{expires}{audio_url} {AUDIO_LINK_SECRET}".encode()).hexdigest()
    return f"{audio_url}?e={expires}&st={sig}"


def _connect():
    conn = psycopg2.connect(**DB_KW, connect_timeout=3)
    conn.set_client_encoding("UTF8")
    return conn


def _get_setting(key: str, default: str) -> str:
    """从 app_settings 读配置"""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def _limit_dict() -> dict:
    """读 app_settings 限流配置 + 用户今日已用秒数 (供其它端点复用)"""
    limit_min = int(_get_setting("book_listen_daily_limit_minutes", str(DEFAULT_LIMIT_MIN)))
    enabled = _get_setting("book_listen_daily_limit_enabled", "true") == "true"
    return {
        "enabled": enabled,
        "limit_minutes": limit_min,
        "limit_source": "app_settings.book_listen_daily_limit_minutes",
    }


def _get_today_used(user_id: int) -> int:
    """读今天已听多少秒"""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT total_seconds FROM book_listen_daily "
            "WHERE user_id=%s AND listen_date=CURRENT_DATE",
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _add_listen_seconds(user_id: int, added_sec: int):
    """累加今日 listen_daily.total_seconds"""
    if added_sec <= 0:
        return
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO book_listen_daily (user_id, listen_date, total_seconds) "
            "VALUES (%s, CURRENT_DATE, %s) "
            "ON CONFLICT (user_id, listen_date) "
            "DO UPDATE SET total_seconds = book_listen_daily.total_seconds + EXCLUDED.total_seconds",
            (user_id, added_sec),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


@router.get("/books")
async def list_books(
    current_user: dict = Depends(get_current_user),
):
    """列出所有有听书音频的书 (含每本书的章节数/总时长 + 用户进度 + 跨书限流)"""
    user_id = int(current_user["user_id"])
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # 1) 每本书汇总
        cur.execute(
            "SELECT serial, COUNT(*) AS chapters, "
            "       COALESCE(SUM(audio_duration), 0) AS total_seconds, "
            "       COALESCE(SUM(explanation_chars), 0) AS total_chars, "
            "       MIN(chapter_idx) AS first_idx, MAX(title) AS first_title "
            "FROM book_chapters "
            "WHERE audio_url IS NOT NULL "
            "GROUP BY serial "
            "ORDER BY serial"
        )
        rows = cur.fetchall()
        # 2) 用户对每本书的进度 (从 BookProgress 读, book_title = "<serial>: <title>")
        cur.execute(
            "SELECT book_title, current_chapter, total_chapters, updated_at "
            "FROM book_progress WHERE user_id=%s",
            (user_id,),
        )
        prog = {p["book_title"]: p for p in cur.fetchall()}
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    books = []
    for i, r in enumerate(rows, 1):
        serial = r["serial"]
        # 尝试匹配进度: 找该 serial 下的任意 chapter 进度
        matched = None
        for bt, p in prog.items():
            if bt.startswith(f"{serial}:"):
                matched = p
                break
        last_chapter = matched["current_chapter"] if matched else 0
        # 计算已听总秒 (估: (last_chapter-1) 章全听完 + 当前章 0)
        listened_sec_est = 0
        if last_chapter > 0:
            try:
                conn = _connect()
                c2 = conn.cursor()
                c2.execute(
                    "SELECT COALESCE(SUM(audio_duration), 0) FROM book_chapters "
                    "WHERE serial=%s AND chapter_idx < %s AND audio_url IS NOT NULL",
                    (serial, last_chapter),
                )
                listened_sec_est = int(c2.fetchone()[0] or 0)
                c2.close()
                conn.close()
            except Exception:
                pass
        total_sec = int(r["total_seconds"])
        progress = round((listened_sec_est / total_sec) * 100) if total_sec > 0 else 0
        books.append({
            "serial": serial,
            "book_index": i,  # 经典书目中按 serial 升序的 1-based 编号
            "chapters": int(r["chapters"]),
            "total_seconds": total_sec,
            "total_chars": int(r["total_chars"]),
            "first_title": r["first_title"],
            "last_chapter": last_chapter,
            "listened_seconds_est": listened_sec_est,
            "progress_percent": progress,
        })

    used_sec = _get_today_used(user_id)
    ld = _limit_dict()
    limit_sec = ld["limit_minutes"] * 60
    remain_sec = max(0, limit_sec - used_sec) if ld["enabled"] else limit_sec
    return {
        "code": 0,
        "data": {
            "books": books,
            "limit": {**ld, "used_seconds": used_sec, "remaining_seconds": remain_sec},
        },
    }


@router.get("/serial/{serial}")
async def list_chapters(
    serial: str,
    current_user: dict = Depends(get_current_user),
):
    """列某本书的所有章节（含 LMS 评析稿 + 音频元数据）"""
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT chapter_idx, title, source_chars, explanation_chars, "
            "       audio_url, audio_duration, status, kind "
            "FROM book_chapters "
            "WHERE serial=%s AND audio_url IS NOT NULL "
            "ORDER BY chapter_idx",
            (serial,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    chapters = [
        {
            "chapter_idx": r["chapter_idx"],
            "title": r["title"],
            "kind": r["kind"],
            "audio_url": make_secure_audio_url(r["audio_url"]) if r["audio_url"] else None,
            "audio_duration": r["audio_duration"],
            "explanation_chars": r["explanation_chars"],
            "source_chars": r["source_chars"],
            "status": r["status"],
        }
        for r in rows
    ]
    return {"code": 0, "data": {"serial": serial, "chapters": chapters}}


@router.get("/serial/{serial}/{idx}")
async def get_chapter(
    serial: str,
    idx: int,
    current_user: dict = Depends(get_current_user),
):
    """拿某章详情（含 explanation 评析稿全文, 用于前端同步高亮）"""
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT chapter_idx, title, kind, explanation, explanation_chars, "
            "       source_chars, audio_url, audio_duration, status "
            "FROM book_chapters "
            "WHERE serial=%s AND chapter_idx=%s",
            (serial, idx),
        )
        r = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    if not r:
        raise HTTPException(status_code=404, detail="chapter not found")

    return {
        "code": 0,
        "data": {
            "chapter_idx": r["chapter_idx"],
            "title": r["title"],
            "kind": r["kind"],
            "explanation": r["explanation"] or "",
            "explanation_chars": r["explanation_chars"],
            "source_chars": r["source_chars"],
            "audio_url": make_secure_audio_url(r["audio_url"]) if r["audio_url"] else None,
            "audio_duration": r["audio_duration"],
            "status": r["status"],
        },
    }


@router.get("/limit")
async def get_limit(
    current_user: dict = Depends(get_current_user),
):
    """查今日剩余可听分钟数 (跨书共用 120min)"""
    ld = _limit_dict()
    used_sec = _get_today_used(int(current_user["user_id"]))
    limit_sec = ld["limit_minutes"] * 60
    remain_sec = max(0, limit_sec - used_sec) if ld["enabled"] else limit_sec
    return {
        "code": 0,
        "data": {**ld, "used_seconds": used_sec, "remaining_seconds": remain_sec},
    }


class ProgressItem(BaseModel):
    chapter_idx: int
    position_sec: int = 0   # 客户端已播放秒数
    listened_sec: int = 0   # 本次会话累计秒数 (用于限流累加)


@router.post("/serial/{serial}/{idx}/progress")
async def save_progress(
    serial: str,
    idx: int,
    item: ProgressItem,
    current_user: dict = Depends(get_current_user),
):
    """记听书进度 + 累加 listen_daily (限流)"""
    user_id = int(current_user["user_id"])

    # 限流校验
    enabled = _get_setting("book_listen_daily_limit_enabled", "true") == "true"
    if enabled and item.listened_sec > 0:
        limit_min = int(_get_setting("book_listen_daily_limit_minutes", str(DEFAULT_LIMIT_MIN)))
        used_sec = _get_today_used(user_id)
        if used_sec + item.listened_sec > limit_min * 60:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "daily_limit_exceeded",
                    "limit_minutes": limit_min,
                    "used_seconds": used_sec,
                    "tried_to_add": item.listened_sec,
                },
            )
        # 累加今日
        _add_listen_seconds(user_id, item.listened_sec)

    # 写 reading_progress (复用 BookProgress, 用 book_title = "<serial>: <title>" 表示 chapter)
    try:
        async with async_session() as session:
            from app.models.cache import BookProgress
            from sqlalchemy import select
            # 查书名
            conn = _connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT title FROM book_chapters WHERE serial=%s AND chapter_idx=%s",
                (serial, idx),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row:
                raise HTTPException(status_code=404, detail="chapter not found")
            book_title = f"{serial}: {row[0]}"
            r = await session.execute(
                select(BookProgress).where(
                    BookProgress.user_id == user_id,
                    BookProgress.book_title == book_title,
                )
            )
            p = r.scalar_one_or_none()
            if p:
                p.current_chapter = idx
                p.total_chapters = max(item.chapter_idx, p.total_chapters or 0)
                p.book_path = f"/app/listen/{serial}/{idx}"
            else:
                session.add(BookProgress(
                    user_id=user_id,
                    book_title=book_title,
                    book_path=f"/app/listen/{serial}/{idx}",
                    total_chapters=item.chapter_idx,
                    current_chapter=idx,
                ))
            await session.flush()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"save error: {e}")

    return {"code": 0, "message": "ok", "data": {"position_sec": item.position_sec}}
