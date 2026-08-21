"""读书进度 API（P2-#13）"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.cache import BookProgress

router = APIRouter(prefix="/api/v1/reading", tags=["读书进度"])


class ProgressSave(BaseModel):
    book_title: str
    book_path: str = ""
    total_chapters: int = 1
    current_chapter: int = 1


@router.get("/progress")
async def get_progress(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户所有读书进度（最近20本）"""
    r = await db.execute(
        select(BookProgress)
        .where(BookProgress.user_id == current_user["user_id"])
        .order_by(BookProgress.updated_at.desc())
        .limit(20)
    )
    items = [{"book_title": p.book_title, "book_path": p.book_path,
              "total_chapters": p.total_chapters, "current_chapter": p.current_chapter,
              "updated_at": p.updated_at.isoformat() if p.updated_at else None}
             for p in r.scalars().all()]
    return {"code": 0, "data": {"progress": items}}


@router.post("/progress")
async def save_progress(
    req: ProgressSave,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """保存/更新读书进度"""
    r = await db.execute(
        select(BookProgress).where(
            BookProgress.user_id == current_user["user_id"],
            BookProgress.book_title == req.book_title,
        )
    )
    p = r.scalar_one_or_none()
    if p:
        p.current_chapter = req.current_chapter
        p.total_chapters = req.total_chapters
        p.book_path = req.book_path or p.book_path
    else:
        db.add(BookProgress(
            user_id=current_user["user_id"],
            book_title=req.book_title,
            book_path=req.book_path,
            total_chapters=req.total_chapters,
            current_chapter=req.current_chapter,
        ))
    await db.flush()
    return {"code": 0, "message": "ok"}


@router.delete("/progress/{book_title}")
async def delete_progress(
    book_title: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除指定书的阅读进度"""
    r = await db.execute(
        select(BookProgress).where(
            BookProgress.user_id == current_user["user_id"],
            BookProgress.book_title == book_title,
        )
    )
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="进度不存在")
    await db.delete(p)
    await db.flush()
    return {"code": 0, "message": "deleted"}
