"""AI 对话 API — 流式响应 + Redis 缓存"""
import json, sys, asyncio, hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from pydantic import BaseModel, Field

sys.path.insert(0, "/root/psy-chat")
from chatbot import chat_stream, chat_once
from rag_search import search_wiki

from app.core.database import async_session
from app.core.security import get_current_user
from app.core.redis import redis_client
from app.models.chat import ChatSession, ChatMessage
from app.models.cache import QACache, UserQACache
from app.services.chat_service import MODE_CONFIG, get_user_sessions, get_session_messages, delete_session

router = APIRouter(prefix="/api/v1/chat", tags=["AI对话"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    session_id: int | None = None
    mode: str = Field(default="science", pattern="^(science|counseling|assessment|reading)$")
    use_rag: bool = True


@router.post("/send")
async def chat_send(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """流式 AI 对话"""
    user_id = current_user["user_id"]
    cfg = MODE_CONFIG.get(req.mode, MODE_CONFIG["science"])
    full_response = ""

    async def event_stream():
        nonlocal full_response
        db = async_session()
        session_id = req.session_id
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

            # RAG 并行检索
            rag_task = None
            if req.use_rag:
                async def _rag():
                    try:
                        data = await asyncio.to_thread(search_wiki, req.message, limit=5 if req.mode != "reading" else 15)
                        results = data.get("results", []) if isinstance(data, dict) else []
                        if results:
                            return "\n\n".join(f"【{r.get('title','参考')}】\n{r.get('snippet', r.get('content',''))[:400]}" for r in results[:5])
                    except Exception:
                        return ""
                    return ""
                rag_task = asyncio.create_task(_rag())

            # 构建消息
            system_content = cfg["system_prompt"]
            api_messages = [{"role": "system", "content": system_content}]
            for msg in history_msgs[-10:]:
                api_messages.append({"role": msg["role"], "content": msg["content"]})
            api_messages.append({"role": "user", "content": req.message})

            if rag_task:
                rag_text = await rag_task
                if rag_text:
                    api_messages[0]["content"] += f"\n\n参考资料：\n{rag_text}"

            # === 三层缓存检查（仅非 RAG 模式） ===
            qhash = hashlib.md5(req.message.encode()).hexdigest()
            cache_key = f"chat:{req.mode}:{qhash}" if (not req.use_rag and len(req.message) >= 4) else None
            cached = None

            if cache_key:
                # 第1层：用户个人缓存（PostgreSQL — 永久有效）
                r = await db.execute(select(UserQACache).where(UserQACache.user_id == user_id, UserQACache.question_hash == qhash, UserQACache.mode == req.mode))
                uqa = r.scalar_one_or_none()
                if uqa:
                    cached = uqa.answer
                else:
                    # 第2层：全局缓存（PostgreSQL — 永久有效，跨用户共享）
                    r = await db.execute(select(QACache).where(QACache.question_hash == qhash, QACache.mode == req.mode))
                    qa = r.scalar_one_or_none()
                    if qa:
                        cached = qa.answer
                        qa.hit_count += 1
                        await db.flush()
                    else:
                        # 第3层：Redis 热缓存（快速）
                        cached = await redis_client.get(cache_key)

                if cached:
                    full_response = cached
                    yield json.dumps({"chunk": cached}, ensure_ascii=False) + "\n"
                    yield json.dumps({"done": True, "session_id": session_id, "cached": True, "sources": []}, ensure_ascii=False) + "\n"
                    # 保存用户个人缓存 + 聊天记录
                    try:
                        if not uqa:
                            db.add(UserQACache(user_id=user_id, mode=req.mode, question_hash=qhash, question=req.message, answer=cached))
                        db.add(ChatMessage(session_id=session_id, role="user", content=req.message))
                        db.add(ChatMessage(session_id=session_id, role="assistant", content=cached))
                        await db.execute(update(ChatSession).where(ChatSession.id == session_id).values(message_count=ChatSession.message_count + 2, updated_at=datetime.now(timezone.utc)))
                        await db.commit()
                    except Exception: await db.rollback()
                    return

            # 流式调用 AI（chat_stream 返回字符串）
            try:
                async for chunk in chat_stream(api_messages, temperature=0.5 if req.mode == "science" else 0.7):
                    full_response += chunk
                    yield json.dumps({"chunk": chunk}, ensure_ascii=False) + "\n"
            except Exception:
                try:
                    full_response = await chat_once(api_messages, temperature=0.5)
                    yield json.dumps({"chunk": full_response}, ensure_ascii=False) + "\n"
                except Exception:
                    yield json.dumps({"chunk": "抱歉，AI 服务暂时不可用。"}, ensure_ascii=False) + "\n"

            # 写入三层缓存
            if cache_key and full_response and len(full_response) > 20:
                # Redis 热缓存
                await redis_client.setex(cache_key, 86400 * 7, full_response)
                # PostgreSQL 持久缓存（永久）
                try:
                    r = await db.execute(select(QACache).where(QACache.question_hash == qhash, QACache.mode == req.mode))
                    if not r.scalar_one_or_none():
                        db.add(QACache(mode=req.mode, question_hash=qhash, question=req.message, answer=full_response))
                    db.add(UserQACache(user_id=user_id, mode=req.mode, question_hash=qhash, question=req.message, answer=full_response))
                    await db.flush()
                except Exception: pass

            # 保存消息
            try:
                db.add(ChatMessage(session_id=session_id, role="user", content=req.message))
                if full_response:
                    db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response))
                await db.execute(update(ChatSession).where(ChatSession.id == session_id).values(message_count=ChatSession.message_count + 2, updated_at=datetime.now(timezone.utc)))
                await db.commit()
            except Exception:
                await db.rollback()

            yield json.dumps({"done": True, "session_id": session_id, "sources": []}, ensure_ascii=False) + "\n"
        except Exception as e:
            await db.rollback()
            yield json.dumps({"error": str(e)}, ensure_ascii=False) + "\n"
        finally:
            await db.close()

    return StreamingResponse(event_stream(), media_type="application/x-ndjson",
                           headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    db = async_session()
    try:
        sessions = await get_user_sessions(current_user["user_id"], db)
        return {"code": 0, "data": [{"id": s.id, "mode": s.mode, "title": s.title, "message_count": s.message_count, "created_at": s.created_at.isoformat() if s.created_at else None, "updated_at": s.updated_at.isoformat() if s.updated_at else None} for s in sessions]}
    finally:
        await db.close()


@router.get("/messages/{session_id}")
async def get_messages(session_id: int, current_user: dict = Depends(get_current_user)):
    db = async_session()
    try:
        messages = await get_session_messages(session_id, current_user["user_id"], db)
        return {"code": 0, "data": [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None} for m in messages]}
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


@router.get("/modes")
async def get_modes():
    return {"code": 0, "data": [{"id": k, "emoji": v["emoji"], "label": v["label"]} for k, v in MODE_CONFIG.items()]}
