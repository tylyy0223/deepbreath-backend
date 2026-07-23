"""心理量表 API — 列表/题目/提交计分/历史"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.chat import ScaleResult
from app.services.scales import (
    SCALES, LIKERT_4, LIKERT_5,
    SDS_QUESTIONS, SAS_QUESTIONS, SCL90_QUESTIONS,
    calc_sds_score, calc_sas_score, calc_scl90_score, get_scl90_highlights,
)
from app.services.credits_service import PRICING, get_balance, charge

router = APIRouter(prefix="/api/v1/scales", tags=["心理量表"])

_QUESTIONS = {
    "sds": [{"num": q, "text": t} for q, t, _ in SDS_QUESTIONS],
    "sas": [{"num": q, "text": t} for q, t, _ in SAS_QUESTIONS],
    "scl90": [{"num": q, "text": t} for q, t in SCL90_QUESTIONS],
}
_OPTIONS = {"sds": LIKERT_4, "sas": LIKERT_4, "scl90": LIKERT_5}
_CALC = {"sds": calc_sds_score, "sas": calc_sas_score, "scl90": calc_scl90_score}


@router.get("")
async def list_scales():
    """量表列表"""
    return {"code": 0, "data": [
        {k: v for k, v in s.items() if k != "score_fn"} for s in SCALES.values()
    ]}


@router.get("/{scale_id}")
async def get_scale(scale_id: str):
    """量表题目与选项"""
    if scale_id not in SCALES:
        raise HTTPException(status_code=404, detail="量表不存在")
    meta = {k: v for k, v in SCALES[scale_id].items() if k != "score_fn"}
    return {"code": 0, "data": {
        **meta,
        "questions": _QUESTIONS[scale_id],
        "options": _OPTIONS[scale_id],
    }}


class ScaleSubmit(BaseModel):
    answers: dict[str, int]  # {"q1": 2, ...}


@router.post("/{scale_id}/submit")
async def submit_scale(
    scale_id: str, req: ScaleSubmit,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交答卷：计分 + 扣费 + 存档"""
    if scale_id not in SCALES:
        raise HTTPException(status_code=404, detail="量表不存在")

    questions = _QUESTIONS[scale_id]
    valid_values = {o["value"] for o in _OPTIONS[scale_id]}
    missing = [q["num"] for q in questions if f"q{q['num']}" not in req.answers]
    if missing:
        raise HTTPException(status_code=400, detail=f"还有 {len(missing)} 题未作答")
    for k, v in req.answers.items():
        if v not in valid_values:
            raise HTTPException(status_code=400, detail=f"{k} 的答案无效")

    cost = PRICING["scale"]
    user_id = current_user["user_id"]
    if await get_balance(db, user_id) < cost:
        raise HTTPException(status_code=402, detail=f"Credits 余额不足（量表测评需 {cost} Credits），请充值后再试")

    result = _CALC[scale_id](req.answers)
    if scale_id == "scl90":
        result["highlights"] = get_scl90_highlights(result)
        raw_score = result["total_raw"]
        standard_score = result["gsi"]
    else:
        raw_score = result["raw_score"]
        standard_score = result["standard_score"]

    record = ScaleResult(
        user_id=user_id, scale_id=scale_id,
        raw_score=raw_score, standard_score=standard_score,
        level=result["level"],
        answers_json=json.dumps(req.answers, ensure_ascii=False),
        result_json=json.dumps(result, ensure_ascii=False),
    )
    db.add(record)
    await charge(db, user_id, cost, ref=f"scale:{scale_id}", note=f"量表测评·{SCALES[scale_id]['name']}")
    await db.flush()

    return {"code": 0, "data": {"result_id": record.id, "scale_id": scale_id, **result}}


@router.get("/history/list")
async def history(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """我的测评历史"""
    r = await db.execute(
        select(ScaleResult).where(ScaleResult.user_id == current_user["user_id"])
        .order_by(ScaleResult.created_at.desc()).limit(50)
    )
    rows = r.scalars().all()
    out = []
    for s in rows:
        meta = SCALES.get(s.scale_id, {})
        out.append({
            "id": s.id, "scale_id": s.scale_id,
            "scale_name": meta.get("name", s.scale_id),
            "emoji": meta.get("emoji", "📝"),
            "raw_score": s.raw_score, "standard_score": s.standard_score,
            "level": s.level,
            "result": json.loads(s.result_json or "{}"),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return {"code": 0, "data": out}
