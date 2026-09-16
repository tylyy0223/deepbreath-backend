"""社区 API — 匿名树洞 + 互助广场"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from app.core.database import get_db
from app.core.security import get_current_user, get_optional_user

router = APIRouter(prefix="/api/v1/community", tags=["社区"])


# ====== TTS 桥接：对话存档时继承已有音频绑定 ======

async def _bridge_tts_binding(db, content: str, new_ref: str):
    """检查 content 是否已有 TTS 音频，如有则桥接绑定到 new_ref"""
    import hashlib
    import os

    CACHE_DIR = "/var/lib/deepbreath/tts"
    VOICE_IDS = ["female-shaonv", "male-qn-qingse"]

    for vid in VOICE_IDS:
        h = hashlib.md5((content + vid).encode()).hexdigest()
        if os.path.isfile(os.path.join(CACHE_DIR, f"mm_{h}.mp3")):
            from app.models.cache import TtsBinding
            from sqlalchemy import select as _sel
            try:
                r = await db.execute(_sel(TtsBinding).where(TtsBinding.ref == new_ref))
                existing = r.scalar_one_or_none()
                if not existing:
                    db.add(TtsBinding(ref=new_ref, text_hash=h))
                    await db.flush()
            except Exception:
                pass
            return  # 找到一个就够


class PostCreate(BaseModel):
    title: str = ""
    content: str = Field(..., min_length=1, max_length=50000)
    category: str = "general"
    is_anonymous: bool = False
    images: list[str] = []


class ReplyCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    is_anonymous: bool = False
    images: list[str] = []


@router.get("/posts/{post_id}")
async def get_post(
    post_id: int,
    current_user: dict | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """帖子详情（含完整内容、作者信息、回复列表）"""
    r = await db.execute(
        select(CommunityPost).where(
            CommunityPost.id == post_id,
            CommunityPost.status == "active",
        )
    )
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    # 浏览量 +1（异步）
    await db.execute(
        update(CommunityPost).where(CommunityPost.id == post_id).values(view_count=CommunityPost.view_count + 1)
    )

    uid = current_user["user_id"] if current_user else None

    # 作者信息
    author = None
    if not post.is_anonymous and post.author_id:
        from app.models.user import User
        ar = await db.execute(select(User).where(User.id == post.author_id))
        au = ar.scalar_one_or_none()
        if au:
            author = {"nickname": au.nickname, "avatar_url": au.avatar_url}

    # 当前用户是否已点赞
    is_liked = False
    if uid:
        lr = await db.execute(
            select(func.count(CommunityLike.id)).where(
                CommunityLike.post_id == post_id,
                CommunityLike.user_id == uid,
            )
        )
        is_liked = lr.scalar() > 0

    # 回复列表
    from app.models.user import User
    replies_r = await db.execute(
        select(CommunityReply).where(
            CommunityReply.post_id == post_id,
        ).order_by(CommunityReply.created_at.asc())
    )
    replies = replies_r.scalars().all()

    reply_list = []
    for rp in replies:
        rp_author = None
        if not rp.is_anonymous and rp.author_id:
            ar2 = await db.execute(select(User).where(User.id == rp.author_id))
            au2 = ar2.scalar_one_or_none()
            if au2:
                rp_author = {"nickname": au2.nickname, "avatar_url": au2.avatar_url}
        reply_list.append({
            "id": rp.id,
            "content": rp.content,
            "is_anonymous": rp.is_anonymous,
            "author_id": rp.author_id,
            "is_mine": uid is not None and rp.author_id == uid,
            "images": getattr(rp, 'images', None) or [],
            "author": rp_author if not rp.is_anonymous else None,
            "created_at": rp.created_at.isoformat() if rp.created_at else None,
        })

    return {
        "code": 0,
        "data": {
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "category": post.category,
            "is_anonymous": post.is_anonymous,
            "author_id": post.author_id,
            "author": author if not post.is_anonymous else None,
            "is_mine": uid is not None and post.author_id == uid,
            "is_liked": is_liked,
            "like_count": post.like_count,
            "reply_count": post.reply_count,
            "view_count": getattr(post, 'view_count', 0) or 0,
            "images": getattr(post, 'images', None) or [],
            "replies": reply_list,
            "created_at": post.created_at.isoformat() if post.created_at else None,
        },
    }


@router.get("/posts")
async def list_posts(
    category: str = Query(default="general"),
    mine: bool = Query(default=False),
    page: int = 1,
    page_size: int = 20,
    current_user: dict | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """帖子列表；mine=true 时仅返回当前用户自己的帖子（需登录）"""
    filters = [CommunityPost.status == "active", CommunityPost.category == category]
    if mine:
        if not current_user:
            raise HTTPException(status_code=401, detail="请先登录")
        filters.append(CommunityPost.author_id == current_user["user_id"])

    q = select(CommunityPost).where(*filters)
    q = q.order_by(CommunityPost.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    r = await db.execute(q)
    posts = r.scalars().all()

    r2 = await db.execute(select(func.count(CommunityPost.id)).where(*filters))
    total = r2.scalar()

    uid = current_user["user_id"] if current_user else None

    # 批量查询当前用户已点赞的帖子 ID
    liked_ids: set[int] = set()
    if uid and posts:
        ids = [p.id for p in posts]
        lr = await db.execute(
            select(CommunityLike.post_id).where(
                CommunityLike.post_id.in_(ids),
                CommunityLike.user_id == uid,
            )
        )
        liked_ids = {row[0] for row in lr.fetchall()}

    return {"code": 0, "data": [
        {"id": p.id, "title": p.title, "content": p.content[:500],
         "is_anonymous": p.is_anonymous, "like_count": p.like_count,
         "reply_count": p.reply_count, "view_count": getattr(p, 'view_count', 0) or 0,
         "category": p.category,
         "images": getattr(p, 'images', None) or [],
         "author_id": p.author_id,
         "is_mine": uid is not None and p.author_id == uid,
         "is_liked": p.id in liked_ids,
         "created_at": p.created_at.isoformat() if p.created_at else None}
        for p in posts
    ], "total": total}


@router.post("/posts")
async def create_post(
    req: PostCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发布帖子（含内容过滤）"""
    from app.services.content_filter import check_content

    if req.title:
        ok, result = check_content(req.title)
        if not ok: raise HTTPException(status_code=400, detail=result)
        req.title = result
    ok, result = check_content(req.content)
    if not ok: raise HTTPException(status_code=400, detail=result)

    post = CommunityPost(
        author_id=current_user["user_id"],
        title=req.title, content=result,
        category=req.category, is_anonymous=req.is_anonymous,
        images=req.images or [],
    )
    db.add(post)
    await db.flush()

    # 发帖奖励 5 Credits
    POST_REWARD = 5
    from app.services.credits_service import add_transaction
    await add_transaction(
        db, current_user["user_id"], POST_REWARD, "reward",
        ref=f"post:{post.id}", note="社区发帖奖励",
    )

    # P1: 桥接 TTS 绑定——对话存档时自动继承已有音频
    if req.category == "article" and req.content:
        await _bridge_tts_binding(db, req.content, f"post:{post.id}")

    return {"code": 0, "data": {"id": post.id, "reward_credits": POST_REWARD}}


@router.post("/posts/{post_id}/like")
async def like_post(
    post_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """点赞/取消点赞"""
    r = await db.execute(select(CommunityLike).where(CommunityLike.post_id == post_id, CommunityLike.user_id == current_user["user_id"]))
    existing = r.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.execute(update(CommunityPost).where(CommunityPost.id == post_id).values(like_count=CommunityPost.like_count - 1))
        action = "unliked"
    else:
        db.add(CommunityLike(post_id=post_id, user_id=current_user["user_id"]))
        await db.execute(update(CommunityPost).where(CommunityPost.id == post_id).values(like_count=CommunityPost.like_count + 1))
        action = "liked"
    await db.flush()
    return {"code": 0, "data": {"action": action}}


@router.post("/posts/{post_id}/reply")
async def reply_post(
    post_id: int,
    req: ReplyCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """回复帖子（含内容过滤）"""
    from app.services.content_filter import check_content
    ok, result = check_content(req.content)
    if not ok: raise HTTPException(status_code=400, detail=result)
    reply = CommunityReply(post_id=post_id, author_id=current_user["user_id"], content=result, is_anonymous=req.is_anonymous, images=req.images or [])
    db.add(reply)
    await db.execute(update(CommunityPost).where(CommunityPost.id == post_id).values(reply_count=CommunityPost.reply_count + 1))
    await db.flush()

    # 回帖奖励 2 Credits
    REPLY_REWARD = 2
    from app.services.credits_service import add_transaction
    await add_transaction(
        db, current_user["user_id"], REPLY_REWARD, "reward",
        ref=f"reply:{reply.id}", note="社区回帖奖励",
    )

    return {"code": 0, "data": {"id": reply.id, "reward_credits": REPLY_REWARD}}


class PostUpdate(BaseModel):
    title: str = ""
    content: str = Field(..., min_length=1, max_length=50000)


@router.put("/posts/{post_id}")
async def update_post(
    post_id: int,
    req: PostUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑帖子（仅作者可编辑）"""
    r = await db.execute(
        select(CommunityPost).where(CommunityPost.id == post_id)
    )
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    if post.author_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权编辑")
    from app.services.content_filter import check_content
    if req.title:
        ok, result = check_content(req.title)
        if not ok: raise HTTPException(status_code=400, detail=result)
        post.title = result
    ok, result = check_content(req.content)
    if not ok: raise HTTPException(status_code=400, detail=result)
    post.content = result
    post.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return {"code": 0, "message": "已更新"}


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除帖子（仅作者可删除）"""
    r = await db.execute(
        select(CommunityPost).where(CommunityPost.id == post_id)
    )
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    if post.author_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权删除")
    post.status = "deleted"
    await db.flush()
    return {"code": 0, "message": "已删除"}


@router.put("/posts/{post_id}/replies/{reply_id}")
async def update_reply(
    post_id: int,
    reply_id: int,
    req: ReplyCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑回复（仅回复作者可编辑）"""
    r = await db.execute(
        select(CommunityReply).where(
            CommunityReply.id == reply_id,
            CommunityReply.post_id == post_id,
        )
    )
    reply = r.scalar_one_or_none()
    if not reply:
        raise HTTPException(status_code=404, detail="回复不存在")
    if reply.author_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权编辑")
    from app.services.content_filter import check_content
    ok, result = check_content(req.content)
    if not ok: raise HTTPException(status_code=400, detail=result)
    reply.content = result
    await db.flush()
    return {"code": 0, "message": "已更新"}


@router.delete("/posts/{post_id}/replies/{reply_id}")
async def delete_reply(
    post_id: int,
    reply_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除回复（仅回复作者可删除）"""
    r = await db.execute(
        select(CommunityReply).where(
            CommunityReply.id == reply_id,
            CommunityReply.post_id == post_id,
        )
    )
    reply = r.scalar_one_or_none()
    if not reply:
        raise HTTPException(status_code=404, detail="回复不存在")
    if reply.author_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权删除")
    await db.delete(reply)
    r2 = await db.execute(select(func.count(CommunityReply.id)).where(CommunityReply.post_id == post_id))
    new_count = r2.scalar() or 0
    await db.execute(
        update(CommunityPost).where(CommunityPost.id == post_id).values(reply_count=new_count)
    )
    await db.flush()
    return {"code": 0, "message": "已删除"}


from app.models.community import CommunityPost, CommunityReply, CommunityLike, CommunityReport  # noqa: E402
