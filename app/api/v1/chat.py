"""AI 对话 API — 流式响应 + Redis 缓存 + QA 缓存"""
import json, sys, asyncio, hashlib, re, os, uuid
import logging as _logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.services.chatbot import chat_stream, chat_once
from app.services.rag_search import search_wiki

from app.core.database import async_session, get_db
from app.core.security import get_current_user
from app.core.redis import redis_client, check_rate_limit
from app.models.chat import ChatSession, ChatMessage
from app.models.cache import QACache
from app.services.chat_service import MODE_CONFIG, get_user_sessions, get_session_messages, delete_session
from app.services.credits_service import chat_cost, get_balance, charge

router = APIRouter(prefix="/api/v1/chat", tags=["AI对话"])

# 防滥用限流：每用户每分钟最多发 CHAT_RATE_LIMIT_PER_MIN 条（.env 可调，默认 20）
CHAT_RATE_LIMIT_PER_MIN = int(os.environ.get("CHAT_RATE_LIMIT_PER_MIN", "20"))
# 在线用户窗口（管理后台并发监控：任一 API 请求刷新此窗口）
ONLINE_WINDOW_SECONDS = 300


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    session_id: int | None = None
    mode: str = Field(default="science", pattern="^(science|counseling|assessment|reading)$")
    use_rag: bool = True
    images: list[str] = []


async def _set_session_title(session_id: int, question: str, db):
    """如果会话标题为空或默认值，用第一个问题作为标题"""
    try:
        r = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        sess = r.scalar_one_or_none()
        if sess and (not sess.title or sess.title == '新对话'):
            title = question[:40] + ('…' if len(question) > 40 else '')
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_id)
                .values(title=title)
            )
    except Exception:
        pass


_BOOK_SERIAL_RE = re.compile(r'(?:编号|第|#|[Nn]o\.?)\s*(\d{1,3})|(\d{1,3})\s*号')


async def _pre_generate_book_tts(text: str, serial: str, user_id: int):
    """后台任务：预生成书介绍的所有音色 TTS 音频"""
    try:
        from app.api.v1.tts import pre_generate_tts
        await pre_generate_tts(text, f"book:{serial}", user_id)
    except Exception:
        pass  # 静默失败，不影响主流程


def _detect_book_serial(message: str) -> str | None:
    """阅读模式：从消息中识别参考文献书目编号（如「学习42号书」「编号107」「#42」）"""
    m = _BOOK_SERIAL_RE.search(message)
    if m:
        return (m.group(1) or m.group(2)).zfill(3)
    return None


async def _save_book_progress(user_id: int, book: dict):
    """后台保存读书进度（P2-#13：自动记录用户报号学书的书籍）"""
    try:
        from app.core.database import async_session as _as
        from app.models.cache import BookProgress
        from sqlalchemy import select as _sel

        title = book.get("name", "")
        if not title:
            return
        db = _as()
        r = await db.execute(
            _sel(BookProgress).where(BookProgress.user_id == user_id, BookProgress.book_title == title)
        )
        existing = r.scalar_one_or_none()
        if existing:
            existing.current_chapter = 1
        else:
            db.add(BookProgress(
                user_id=user_id, book_title=title,
                book_path=book.get("path", ""),
                total_chapters=book.get("chapters", 1),
                current_chapter=1,
            ))
        await db.commit()
    except Exception:
        pass  # 静默——不影响主对话


@router.post("/send")
async def chat_send(req: ChatRequest, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """流式 AI 对话（httpx 连接池复用版）"""
    # user_id 在函数体最顶部赋值（event_stream 是嵌套 async generator 闭包引用 user_id）
    user_id = current_user["user_id"]

    # 防滥用限流
    if not await check_rate_limit(f"chat:rl:{user_id}", CHAT_RATE_LIMIT_PER_MIN, 60):
        try:
            await redis_client.incr("stats:chat:rate_limited")
        except Exception:
            pass
        raise HTTPException(status_code=429, detail=f"发送太频繁，请稍等片刻再试（每分钟最多 {CHAT_RATE_LIMIT_PER_MIN} 条）")

    # 在线追踪
    try:
        await redis_client.set(f"online:{user_id}", int(datetime.now(timezone.utc).timestamp()), ex=ONLINE_WINDOW_SECONDS)
    except Exception:
        pass

    # 余额预检
    cost = chat_cost(req.mode)
    bal = await get_balance(db, user_id)
    if bal < cost:
        raise HTTPException(status_code=402, detail=f"Credits 余额不足（本次对话需 {cost} Credits），请充值后再试")

    # === 内嵌 event_stream（作为 chat_send 的嵌套 async generator） ===
    async def event_stream():
        nonlocal_full_response_placeholder = None  # 占位，下面覆盖
        # 实际 nonlocal 变量
        full_response = ""
        cost_ = cost

        # StreamingResponse 生命周期长于路由依赖注入，必须自建 session
        db = async_session()
        session_id = req.session_id
        # 标记用户正在 AI 对话中（流结束清除）
        try:
            await redis_client.set(f"ai_active:{user_id}", int(datetime.now(timezone.utc).timestamp()), ex=120)
        except Exception:
            pass
        try:
            if not session_id:
                s = ChatSession(user_id=user_id, mode=req.mode)
                db.add(s); await db.flush()
                session_id = s.id
            else:
                r = await db.execute(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id))
                if not r.scalar_one_or_none():
                    yield json.dumps({"error": "会话不存在"}, ensure_ascii=False) + "\n"; return

            # 加载历史
            history_msgs = []
            if session_id:
                r = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.desc()).limit(20))
                for msg in reversed(r.scalars().all()):
                    history_msgs.append({"role": msg.role, "content": msg.content})

            # 阅读模式：识别书目
            book = None
            book_excerpts = []
            if req.mode == "reading":
                serial = _detect_book_serial(req.message)
                if serial:
                    from app.api.v1.references import find_book_by_serial, get_book_excerpts
                    book = await asyncio.to_thread(find_book_by_serial, serial)
                    if book:
                        asyncio.create_task(_save_book_progress(user_id, book))
                        inner_q = _BOOK_SERIAL_RE.sub("", req.message)
                        inner_q = re.sub(r"[学习研究阅读这本书籍，。！？\s]+", "", inner_q)
                        book_excerpts = await asyncio.to_thread(
                            get_book_excerpts, serial, inner_q if len(inner_q) >= 2 else "", 8
                        )

            # RAG 双通道并行检索
            rag_task = None
            if req.use_rag and not book and req.mode != "assessment":
                from app.services.vector_search import search as vector_search
                async def _rag():
                    try:
                        limit = 5 if req.mode != "reading" else 15
                        vec_data = await asyncio.to_thread(vector_search, req.message, limit=limit)
                        used = set()
                        blocks = []
                        for r in (vec_data.get("results", []) if isinstance(vec_data, dict) else []):
                            t = r.get("title", "")
                            if t in used: continue
                            used.add(t)
                            blocks.append(f"【{t}】\n{r.get('snippet', r.get('content', ''))[:400]}")
                        like_data = await asyncio.to_thread(search_wiki, req.message, limit=limit)
                        for r in (like_data.get("results", []) if isinstance(like_data, dict) else []):
                            t = r.get("title", "")
                            if t in used: continue
                            used.add(t)
                            blocks.append(f"【{t}】\n{r.get('snippet', r.get('content', ''))[:400]}")
                        if blocks:
                            return "\n\n".join(blocks[:8])
                    except Exception:
                        return ""
                    return ""
                rag_task = asyncio.create_task(_rag())

            # QACache 检查
            qa_hash = hashlib.sha256(req.message.encode()).hexdigest()
            qa = None
            if req.mode != "assessment":
                qa_cached = await db.execute(
                    select(QACache).where(QACache.mode == req.mode, QACache.question_hash == qa_hash)
                )
                qa = qa_cached.scalar_one_or_none()
            if qa:
                qa.hit_count += 1
                qa.last_hit_at = datetime.now(timezone.utc)
                full_response = qa.answer
                await db.flush()
                yield json.dumps({"chunk": full_response}, ensure_ascii=False) + "\n"
                yield json.dumps({"done": True, "session_id": session_id, "cached": True, "cost": 0, "sources": []}, ensure_ascii=False) + "\n"
                try:
                    db.add(ChatMessage(session_id=session_id, role="user", content=req.message, images=req.images or []))
                    db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response))
                    await _set_session_title(session_id, req.message, db)
                    await db.execute(update(ChatSession).where(ChatSession.id == session_id).values(message_count=ChatSession.message_count + 2, updated_at=datetime.now(timezone.utc)))
                    await db.commit()
                except Exception: await db.rollback()
                return

            # 构建消息
            cfg = MODE_CONFIG.get(req.mode, MODE_CONFIG["science"])
            system_content = cfg["system_prompt"]
            if req.mode == "assessment" and len(history_msgs) <= 2:
                try:
                    from app.services.assessment_service import (
                        get_user_assessment_history, build_personalized_context,
                    )
                    _hist = await get_user_assessment_history(db, user_id, limit=3)
                    _ctx = build_personalized_context(_hist)
                    if _ctx:
                        system_content += _ctx
                except Exception:
                    pass
            api_messages = [{"role": "system", "content": system_content}]
            prev_role = None
            for msg in history_msgs[-10:]:
                role = msg["role"]
                content = msg["content"]
                if role == "user" and prev_role == "user":
                    api_messages[-1]["content"] += "\n" + content
                    continue
                api_messages.append({"role": role, "content": content})
                prev_role = role
            api_messages.append({"role": "user", "content": req.message})

            if book:
                note = (
                    f"\n\n当前学习书目：《{book['name']}》"
                    + (f"（作者：{book['author']}）" if book['author'] else "")
                    + f"，参考文献编号 {book['seg'][:7]}，共 {book['chapters']} 个章节页。"
                    "用户希望围绕这本书进行整书学习和研究。请基于以下书中原文内容回答；"
                    "如果用户只报了编号没提具体问题，请先介绍本书的主题、结构和核心观点，并给出学习建议。"
                )
                if book_excerpts:
                    note += "\n\n书中内容摘录：\n" + "\n\n".join(
                        f"【{e['title']}】\n{e['excerpt']}" for e in book_excerpts
                    )
                api_messages[0]["content"] += note
            elif rag_task:
                rag_text = await rag_task
                if rag_text:
                    api_messages[0]["content"] += f"\n\n参考资料：\n{rag_text}"

            # Redis 缓存
            cache_key = None
            if not req.use_rag and req.mode != "assessment" and len(req.message) >= 4:
                cache_key = f"chat:{req.mode}:{qa_hash}"
                cached = await redis_client.get(cache_key)
                if cached:
                    full_response = cached
                    yield json.dumps({"chunk": cached}, ensure_ascii=False) + "\n"
                    yield json.dumps({"done": True, "session_id": session_id, "cached": True, "cost": 0, "sources": []}, ensure_ascii=False) + "\n"
                    try:
                        db.add(ChatMessage(session_id=session_id, role="user", content=req.message, images=req.images or []))
                        db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response))
                        await _set_session_title(session_id, req.message, db)
                        await db.execute(update(ChatSession).where(ChatSession.id == session_id).values(message_count=ChatSession.message_count + 2, updated_at=datetime.now(timezone.utc)))
                        await db.commit()
                    except Exception: await db.rollback()
                    return

            # 流式调用 AI
            try:
                async for chunk in chat_stream(api_messages, temperature=0.5 if req.mode == "science" else 0.7, prompt_cache_key=f"deepseek-v4-flash:{req.mode}"):
                    typ = chunk.get("type", "")
                    if typ == "chunk":
                        full_response += chunk["content"]
                        yield json.dumps({"chunk": chunk["content"]}, ensure_ascii=False) + "\n"
                    elif typ == "usage":
                        pass  # cost 暂不用 token 计费
            except Exception as e:
                # 流式失败 fallback 到非流式
                err_id = uuid.uuid4().hex[:12]
                _logging.getLogger(__name__).exception(f"[chat SSE fallback {err_id}] user_id={user_id}: {e}")
                try:
                    full_response = await chat_once(api_messages, temperature=0.5 if req.mode == "science" else 0.7, prompt_cache_key=f"deepseek-v4-flash:{req.mode}")
                    yield json.dumps({"chunk": full_response}, ensure_ascii=False) + "\n"
                except Exception:
                    yield json.dumps({"chunk": "抱歉，AI 服务暂时不可用，请稍后重试。"}, ensure_ascii=False) + "\n"
                    full_response = ""

            # 保存到 DB
            try:
                db.add(ChatMessage(session_id=session_id, role="user", content=req.message, images=req.images or []))
                if full_response:
                    db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response))
                await _set_session_title(session_id, req.message, db)
                await db.execute(update(ChatSession).where(ChatSession.id == session_id).values(message_count=ChatSession.message_count + 2, updated_at=datetime.now(timezone.utc)))
                await db.commit()

                # 扣费
                try:
                    await charge(db, user_id, cost, f"chat:{req.mode}")
                except Exception:
                    pass
            except Exception:
                await db.rollback()

            yield json.dumps({"done": True, "session_id": session_id, "cost": cost, "sources": []}, ensure_ascii=False) + "\n"
        finally:
            # 清除 AI 对话中标记
            try:
                await redis_client.delete(f"ai_active:{user_id}")
            except Exception:
                pass
            await db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")



@router.get("/sessions")
async def list_sessions(
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_current_user),
):
    db = async_session()
    try:
        from sqlalchemy import func
        # Total count
        total_r = await db.execute(
            select(func.count(ChatSession.id)).where(ChatSession.user_id == current_user["user_id"])
        )
        total = total_r.scalar() or 0

        sessions = await get_user_sessions(current_user["user_id"], db, page=page, page_size=page_size)
        data = [{"id": s.id, "mode": s.mode, "title": s.title, "message_count": s.message_count, "created_at": s.created_at.isoformat() if s.created_at else None, "updated_at": s.updated_at.isoformat() if s.updated_at else None} for s in sessions]
        return {"code": 0, "data": data, "total": total, "page": page, "page_size": page_size}
    finally:
        await db.close()


@router.get("/messages/{session_id}")
async def get_messages(session_id: int, current_user: dict = Depends(get_current_user)):
    db = async_session()
    try:
        messages = await get_session_messages(session_id, current_user["user_id"], db)
        return {"code": 0, "data": [{"id": m.id, "role": m.role, "content": m.content, "images": getattr(m, 'images', None) or [], "created_at": m.created_at.isoformat() if m.created_at else None} for m in messages]}
    finally:
        await db.close()


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: int, current_user: dict = Depends(get_current_user)):
    db = async_session()
    try:
        ok = await delete_session(session_id, current_user["user_id"], db)
        if not ok: raise HTTPException(status_code=404, detail="会话不存在")
        await db.commit()
        return {"code": 0, "message": "已删除"}
    finally:
        await db.close()


# ====== P1-#12: 异步 RAG 推荐文章 ======

@router.get("/sessions/{session_id}/related")
async def related_articles(
    session_id: int,
    current_user: dict = Depends(get_current_user),
):
    """根据最近对话内容检索 Wiki 相关文章（异步，不阻塞主回复流）"""
    from app.services.rag_search import search_wiki

    db = async_session()
    try:
        from sqlalchemy import select as _sel
        # 归属校验：防止越权读取他人会话
        owner_check = await db.execute(
            _sel(ChatSession.id).where(
                ChatSession.id == session_id,
                ChatSession.user_id == current_user["user_id"],
            )
        )
        if not owner_check.scalar_one_or_none():
            await db.close()
            return {"code": 0, "data": {"articles": [], "total": 0}}

        r = await db.execute(
            _sel(ChatMessage.content)
            .where(ChatMessage.session_id == session_id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.desc())
            .limit(3)
        )
        recent = [row[0] for row in r.fetchall() if row[0]]
        await db.close()

        if not recent:
            return {"code": 0, "data": {"articles": [], "total": 0}}

        # 只取最近一条用户消息作为检索词（拼接会引入 AI 回复噪音，导致全文匹配失败）
        query = recent[0][:200]
        result = search_wiki(query, limit=4)
        return {"code": 0, "data": {"articles": result.get("results", []), "total": result.get("total", 0)}}
    except Exception:
        return {"code": 0, "data": {"articles": [], "total": 0}}


@router.get("/modes")
async def get_modes():
    return {"code": 0, "data": [{"id": k, "emoji": v["emoji"], "label": v["label"]} for k, v in MODE_CONFIG.items()]}
