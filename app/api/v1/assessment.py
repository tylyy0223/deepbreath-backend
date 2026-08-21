"""心理评估记录 API — 评估历史查询、个人档案"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.assessment_service import get_user_assessment_history

router = APIRouter(prefix="/api/v1/assessment", tags=["心理评估"])


@router.get("/records")
async def assessment_records(
    limit: int = Query(default=5, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户最近的评估记录（最新在前）"""
    user_id = current_user["user_id"]
    records = await get_user_assessment_history(db, user_id, limit=limit)
    return {"code": 0, "data": records, "total": len(records)}


@router.get("/latest")
async def latest_assessment(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户最近一次评估（供前端展示档案卡）"""
    user_id = current_user["user_id"]
    records = await get_user_assessment_history(db, user_id, limit=1)
    if not records:
        return {"code": 0, "data": None}
    return {"code": 0, "data": records[0]}
