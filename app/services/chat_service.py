"""AI 对话服务 — 优化版：DB 操作后台化，优先流式响应"""
import json
import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.chat import ChatSession, ChatMessage
from app.services.chatbot import chat_stream, chat_once
from app.services.rag_search import search_wiki

MODE_CONFIG = {
    "science": {
        "emoji": "\U0001f9e0", "label": "\U0001f9e0 心理科普",
        "system_prompt": "你是一位专业的心理学知识科普助手。用通俗易懂的语言解释心理学概念、理论和实验。保持客观、科学、温暖的态度。回复使用中文。",
    },
    "counseling": {
        "emoji": "\U0001f333", "label": "\U0001f333 心理树洞",
        "system_prompt": "你是一个温暖的「心理树洞」——像大树上那个安静的小洞，你倾听、包容、不评判。用户可以对着你说出心里话，不用担心被批评或泄露。你的角色是帮助释放压力、整理情绪，给予理解与共情。绝不提供临床诊断。保持温暖、安全、非评判的态度。回复使用中文。",
    },
    "assessment": {
        "emoji": "\U0001f4cb", "label": "\U0001f4cb 心理测评",
        "system_prompt": (
            "你是一位结构化心理评估引导者，通过多轮对话帮用户完成一次系统的心理状态评估。\n"
            "【多轮引导协议——必须严格遵守】\n"
            "1. 一次只问一个问题。每轮回复只聚焦当前维度，不要一次抛出多个问题，不要让用户感到被审问。\n"
            "2. 评估维度按顺序推进：情绪状态 → 睡眠与饮食 → 认知与思维 → 社交与人际 → 压力与应对。每个维度用 1-2 个问题即可，不要在一个维度上反复追问。\n"
            "3. 先共情再提问：收到用户回答后，先用一句话共情/确认（如『谢谢你的坦诚』），然后自然过渡到下一个问题。\n"
            "4. 如果用户答非所问或偏离主题，温和地拉回：先接住用户的话，再回到评估主线（如『听起来这件事确实让人焦虑。为了帮你更完整地评估，我想再问一下……』）。\n"
            "5. 如果用户情绪强烈或表达痛苦（如自杀意念），立即停止评估流程，表达关怀，并建议拨打心理援助热线（如 400-161-9995），不要继续提问。\n"
            "6. 【维度推进纪律】当用户没有回答当前维度而讲了其他内容时：先共情接住，然后继续推进到下一个维度，不要反复追问同一个问题。把未回答的维度记在心里，在总结阶段统一补问一次；如果补问后用户仍没回答，就在总结中标注『该维度信息不足』，不要第三次追问。\n"
            "7. 完成 5 个维度后（约 8-10 轮，含总结前的补问），给出结构化总结。总结必须包含以下字段，用清晰的段落呈现：\n"
            "   【分维度概述】：情绪/睡眠饮食/认知/社交/压力 各维度观察到的情况（信息不足的维度标注『信息不足』）\n"
            "   【总体状态判断】：如『状态良好』『轻度困扰』『中度困扰』『需要关注』，并说明依据\n"
            "   【风险提示】：如有自杀意念/自伤风险明确标注『高风险』并建议立即求助；无则写『未发现紧急风险』\n"
            "   【具体建议】：2-3 条可操作建议\n"
            "   【免责声明】：『这不构成临床诊断，如有需要建议寻求专业帮助』\n"
            "8. 回复保持简短（每轮不超过 150 字），使用中文，语气温暖、专业、不评判。\n"
            "9. 整个评估过程中记住用户已经回答过的内容，不要重复提问，不要前后矛盾。\n"
        ),
    },
    "reading": {
        "emoji": "\U0001f4da", "label": "\U0001f4da 读书助手",
        "system_prompt": "你是一位心理学读书导师。帮用户理解书中核心概念，联系实际生活。保持专业、有深度的态度。回复使用中文。",
    },
}


async def send_message(
    user_id: int,
    session_id: int,
    message: str,
    mode: str = "science",
    use_rag: bool = True,
    db: AsyncSession | None = None,
):
    """发送消息并流式返回 AI 回复"""
    if mode not in MODE_CONFIG:
        mode = "science"
    cfg = MODE_CONFIG[mode]

    # RAG 检索后台启动（不依赖 DB session，与 DeepSeek API 调用并行）
    async def do_rag():
        if not use_rag: return ""
        try:
            data = await asyncio.to_thread(search_wiki, message, limit=5 if mode != "reading" else 15)
            results = data.get("results", []) if isinstance(data, dict) else []
            if results:
                parts = [f"【{r.get('title', '参考')}】\n{r.get('snippet', r.get('content', ''))[:400]}" for r in results[:5]]
                return "\n\n".join(parts)
        except Exception:
            return ""
        return ""

    rag_task = asyncio.create_task(do_rag())

    # DB 历史：快速加载最近消息
    history_msgs = []
    if db and session_id:
        result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.desc()).limit(20)
        )
        history_msgs = list(reversed(result.scalars().all()))

    rag_context = await rag_task

    # 构建消息
    api_messages = [{"role": "system", "content": cfg["system_prompt"]}]
    if rag_context:
        api_messages[0]["content"] += f"\n\n参考资料：\n{rag_context}"
    for msg in history_msgs[-10:]:
        api_messages.append({"role": msg.role, "content": msg.content})
    api_messages.append({"role": "user", "content": message})

    # 流式调用 AI
    full_response = ""
    total_tokens = 0
    sources = []
    try:
        async for chunk in chat_stream(messages=api_messages, temperature=0.7 if mode != "reading" else 0.3):
            typ = chunk.get("type", "")
            if typ == "chunk":
                full_response += chunk["content"]
                yield {"chunk": chunk["content"]}
            elif typ == "sources":
                sources = chunk.get("sources", [])
            elif typ == "usage":
                total_tokens = chunk.get("total_tokens", 0)
    except Exception:
        try:
            full_response = await chat_once(api_messages, temperature=0.7 if mode != "reading" else 0.3)
            yield {"chunk": full_response}
        except Exception:
            yield {"chunk": "抱歉，AI 服务暂时不可用，请稍后重试。"}

    # 后台保存（不阻塞响应）
    if db and session_id:
        try:
            db.add(ChatMessage(session_id=session_id, role="user", content=message))
            if full_response:
                db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response,
                       token_count=total_tokens or len(full_response)))  # 真实 token 计数，降级为字符数
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_id)
                .values(message_count=ChatSession.message_count + 2, updated_at=datetime.now(timezone.utc))
            )
            await db.flush()
        except Exception:
            pass

    yield {"done": True, "session_id": session_id, "sources": sources}


async def get_user_sessions(user_id: int, db: AsyncSession, page: int = 1, page_size: int = 20) -> list:
    result = await db.execute(
        select(ChatSession).where(ChatSession.user_id == user_id).order_by(ChatSession.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return result.scalars().all()


async def get_session_messages(session_id: int, user_id: int, db: AsyncSession) -> list:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id))
    if not result.scalar_one_or_none():
        return []
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    )
    return result.scalars().all()


async def delete_session(session_id: int, user_id: int, db: AsyncSession) -> bool:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id))
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        return True
    return False
