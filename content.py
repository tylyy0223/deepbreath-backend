"""科普内容 API — 文章分类/列表/详情"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from app.core.database import get_db
from app.core.security import get_current_user, get_optional_user, require_role, Roles
from app.models.content import Article, Category, Tag
from app.models.diary import MoodEntry

router = APIRouter(prefix="/api/v1/content", tags=["科普内容"])


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    """分类列表"""
    r = await db.execute(select(Category).where(Category.status == "active").order_by(Category.sort_order))
    cats = r.scalars().all()
    return {"code": 0, "data": [{"id": c.id, "name": c.name, "slug": c.slug, "icon": c.icon} for c in cats]}


@router.get("/articles")
async def list_articles(
    category: str = Query(None),
    page: int = 1,
    page_size: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """文章列表（公开）"""
    q = select(Article).where(Article.status == "published")
    if category:
        q = q.join(Category).where(Category.slug == category)
    q = q.order_by(Article.published_at.desc()).offset((page - 1) * page_size).limit(page_size)
    r = await db.execute(q)
    articles = r.scalars().all()

    # 统计总数（需与列表查询保持一致的 category 过滤）
    count_q = select(func.count(Article.id)).where(Article.status == "published")
    if category:
        count_q = count_q.join(Category).where(Category.slug == category)
    r2 = await db.execute(count_q)
    total = r2.scalar()

    return {
        "code": 0,
        "data": [
            {
                "id": a.id, "title": a.title, "slug": a.slug,
                "summary": a.summary, "cover_url": a.cover_url,
                "view_count": a.view_count, "is_featured": a.is_featured,
                "published_at": a.published_at.isoformat() if a.published_at else None,
            }
            for a in articles
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/articles/{slug}")
async def get_article(slug: str, db: AsyncSession = Depends(get_db)):
    """文章详情"""
    r = await db.execute(select(Article).where(Article.slug == slug, Article.status == "published"))
    a = r.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="文章不存在")
    a.view_count += 1
    await db.flush()
    return {"code": 0, "data": {"id": a.id, "title": a.title, "content": a.content, "summary": a.summary, "cover_url": a.cover_url, "view_count": a.view_count, "published_at": a.published_at.isoformat() if a.published_at else None}}


# 情绪均值 → 推荐分类的映射
_MOOD_CATEGORY_MAP = [
    (2.5, "low-mood", "最近情绪有些低落，这些内容或许能陪伴你 🌧"),
    (3.5, "stress-relief", "帮你更好地应对压力与焦虑 🌿"),
    (99.0, "positive-growth", "状态不错！继续探索积极成长 🌱"),
]


@router.get("/recommendations")
async def recommend_articles(
    limit: int = Query(default=6, le=20),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按用户近 7 天情绪均值推荐文章；无日记数据时返回精选文章"""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    r = await db.execute(
        select(func.avg(MoodEntry.mood_score))
        .where(MoodEntry.user_id == current_user["user_id"], MoodEntry.created_at >= since)
    )
    mood_avg = r.scalar()

    q = select(Article).where(Article.status == "published")
    if mood_avg is None:
        reason = "为你精选的心理科普内容 ✨"
        q = q.where(Article.is_featured == True)  # noqa: E712
    else:
        mood_avg = round(float(mood_avg), 1)
        for threshold, slug, desc in _MOOD_CATEGORY_MAP:
            if mood_avg < threshold:
                reason = desc
                q = q.join(Category).where(Category.slug == slug)
                break
    q = q.order_by(Article.published_at.desc()).limit(limit)
    articles = (await db.execute(q)).scalars().all()

    return {"code": 0, "data": {
        "reason": reason,
        "mood_avg": mood_avg,
        "articles": [
            {"id": a.id, "title": a.title, "slug": a.slug, "summary": a.summary,
             "cover_url": a.cover_url, "view_count": a.view_count,
             "published_at": a.published_at.isoformat() if a.published_at else None}
            for a in articles
        ],
    }}
