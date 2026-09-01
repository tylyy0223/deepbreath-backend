"""AI 听书讲解 - 章节列表 / 详情 / 进度 / 限流（v3 严格限流版）"""
import os
import re
import time
import hashlib
import base64
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

# ---- 音频签名 (nginx secure_link) ----
AUDIO_SECRET = "deepbreath_audio_2026"
AUDIO_TTL = 3600  # 签名 1 小时有效


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
    """读 app_settings 限流配置"""
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


def _try_add_listen_seconds(user_id: int, added_sec: int, limit_sec: int):
    """原子检查+累加今日时长（FOR UPDATE 行锁）。返回 (是否成功, 新总量)。"""
    conn = None
    cur = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT total_seconds FROM book_listen_daily "
            "WHERE user_id=%s AND listen_date=CURRENT_DATE FOR UPDATE",
            (user_id,),
        )
        row = cur.fetchone()
        used = int(row[0]) if row else 0
        new_used = used + added_sec
        if new_used > limit_sec:
            conn.rollback()
            return False, used
        if row:
            cur.execute(
                "UPDATE book_listen_daily SET total_seconds=%s "
                "WHERE user_id=%s AND listen_date=CURRENT_DATE",
                (new_used, user_id),
            )
        else:
            cur.execute(
                "INSERT INTO book_listen_daily (user_id, listen_date, total_seconds) "
                "VALUES (%s, CURRENT_DATE, %s)",
                (user_id, added_sec),
            )
        conn.commit()
        return True, new_used
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return False, _get_today_used(user_id)
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _sign_audio(url: str) -> str:
    """生成 nginx secure_link 签名 URL（st/e 参数，AUDIO_TTL 秒有效）"""
    if not url or not url.startswith("/"):
        return url
    e = int(time.time()) + AUDIO_TTL
    raw = f"{e}{url} {AUDIO_SECRET}"
    md5 = hashlib.md5(raw.encode("utf-8")).digest()
    st = base64.urlsafe_b64encode(md5).rstrip(b"=").decode()
    return f"{url}?st={st}&e={e}"


def _limit_state(user_id: int) -> dict:
    """当前限流状态"""
    ld = _limit_dict()
    used_sec = _get_today_used(user_id)
    limit_sec = ld["limit_minutes"] * 60
    remain_sec = max(0, limit_sec - used_sec) if ld["enabled"] else limit_sec
    return {**ld, "used_seconds": used_sec, "remaining_seconds": remain_sec}


def _audio_for(user_id: int, url: str, duration: int):
    """播放前检查：剩余额度足够才给签名音频，否则返回 None（前端无有效音频可播）"""
    if not url:
        return None, _limit_state(user_id)
    st = _limit_state(user_id)
    if st["enabled"] and st["remaining_seconds"] < duration:
        return None, st
    return _sign_audio(url), st


@router.get("/books")
async def list_books(
    current_user: dict = Depends(get_current_user),
):
    """列出所有有听书音频的书 (含每本书的章节数/总时长 + 用户进度 + 跨书限流)"""
    user_id = int(current_user["user_id"])
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
    for r in rows:
        serial = r["serial"]
        matched = None
        for bt, p in prog.items():
            if bt.startswith(f"{serial}:"):
                matched = p
                break
        last_chapter = matched["current_chapter"] if matched else 0
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
            "chapters": int(r["chapters"]),
            "total_seconds": total_sec,
            "total_chars": int(r["total_chars"]),
            "first_title": r["first_title"],
            "last_chapter": last_chapter,
            "listened_seconds_est": listened_sec_est,
            "progress_percent": progress,
        })

    st = _limit_state(user_id)
    return {"code": 0, "data": {"books": books, "limit": st}}


@router.get("/serial/{serial}")
async def list_chapters(
    serial: str,
    current_user: dict = Depends(get_current_user),
):
    """列某本书的所有章节（音频 URL 已签名；剩余额度不足的章节 audio_url 为 null）"""
    user_id = int(current_user["user_id"])
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

    st = _limit_state(user_id)
    chapters = []
    for r in rows:
        dur = int(r["audio_duration"] or 0)
        if st["enabled"] and st["remaining_seconds"] < dur:
            audio = None  # 额度不足，不给可播音频
        else:
            audio = _sign_audio(r["audio_url"])
        chapters.append({
            "chapter_idx": r["chapter_idx"],
            "title": r["title"],
            "kind": r["kind"],
            "audio_url": audio,
            "audio_duration": dur,
            "explanation_chars": r["explanation_chars"],
            "source_chars": r["source_chars"],
            "status": r["status"],
        })
    return {"code": 0, "data": {"serial": serial, "chapters": chapters, "limit": st}}


@router.get("/serial/{serial}/{idx}")
async def get_chapter(
    serial: str,
    idx: int,
    current_user: dict = Depends(get_current_user),
):
    """拿某章详情（含 explanation 评析稿全文；播放前检查剩余额度并签名音频）"""
    user_id = int(current_user["user_id"])
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

    dur = int(r["audio_duration"] or 0)
    audio, st = _audio_for(user_id, r["audio_url"], dur)
    return {
        "code": 0,
        "data": {
            "chapter_idx": r["chapter_idx"],
            "title": r["title"],
            "kind": r["kind"],
            "explanation": r["explanation"] or "",
            "explanation_chars": r["explanation_chars"],
            "source_chars": r["source_chars"],
            "audio_url": audio,
            "audio_duration": dur,
            "status": r["status"],
            "limit": st,
        },
    }


@router.get("/limit")
async def get_limit(
    current_user: dict = Depends(get_current_user),
):
    """查今日剩余可听分钟数 (跨书共用 120min)"""
    return {"code": 0, "data": _limit_state(int(current_user["user_id"]))}


class ProgressItem(BaseModel):
    chapter_idx: int
    position_sec: int = 0   # 客户端已播放秒数
    listened_sec: int = 0   # 本次上报增量秒数 (用于限流累加)


@router.post("/serial/{serial}/{idx}/progress")
async def save_progress(
    serial: str,
    idx: int,
    item: ProgressItem,
    current_user: dict = Depends(get_current_user),
):
    """记听书进度 + 累加 listen_daily (限流)。原子累加 + 单次上报上限校验。"""
    user_id = int(current_user["user_id"])
    enabled = _get_setting("book_listen_daily_limit_enabled", "true") == "true"
    limit_min = int(_get_setting("book_listen_daily_limit_minutes", str(DEFAULT_LIMIT_MIN)))
    limit_sec = limit_min * 60

    # 本章时长（用于单次上报上限校验，防伪造/重试重复累加）
    duration = 0
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT audio_duration FROM book_chapters WHERE serial=%s AND chapter_idx=%s",
            (serial, idx),
        )
        row = cur.fetchone()
        duration = int(row[0] or 0) if row else 0
        cur.close()
        conn.close()
    except Exception:
        pass
    max_once = max(duration * 1.5, 60)  # 单次上报不得超过 1.5 倍章长（至少 60s 容差）
    if item.listened_sec > max_once:
        item.listened_sec = 0  # 异常值不参与限流累加（进度仍保存）

    # 写 reading_progress（先写进度，成功后才累加限流）
    try:
        async with async_session() as session:
            from app.models.cache import BookProgress
            from sqlalchemy import select
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

    # 进度保存成功后才原子累加限流
    if enabled and item.listened_sec > 0:
        ok, new_used = _try_add_listen_seconds(user_id, item.listened_sec, limit_sec)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "daily_limit_exceeded",
                    "limit_minutes": limit_min,
                    "used_seconds": new_used,
                    "tried_to_add": item.listened_sec,
                },
            )

    return {"code": 0, "message": "ok", "data": {"position_sec": item.position_sec}}
