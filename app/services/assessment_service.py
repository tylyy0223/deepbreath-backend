"""心理评估数据持久化服务

职责：
1. 解析 AI 生成的结构化总结 → 提取总体状态/风险/分维度/建议
2. 保存评估记录到 assessment_records 表
3. 提供用户历史评估查询（供个性化上下文注入）
"""
import json, re
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import AssessmentRecord

CN_TZ = timezone(timedelta(hours=8))

# 总体状态判断关键词映射
_STATUS_KEYWORDS = [
    ("需要关注", ["需要关注", "需关注", "高风险", "严重", "重度", "较重"]),
    ("中度困扰", ["中度", "中等", "中程度"]),
    ("轻度困扰", ["轻度", "轻微", "轻程度"]),
    ("状态良好", ["良好", "正常", "平稳", "健康", "不错"]),
]

# 风险关键词
_RISK_HIGH = ["高风险", "自杀", "自伤", "轻生", "结束生命", "不想活", "伤害自己", "危机"]
_RISK_NONE = ["未发现紧急风险", "无风险", "未见风险", "无紧急风险"]


def parse_assessment_summary(summary: str) -> dict:
    """从 AI 结构化总结中解析出可落库的结构化数据

    Returns:
        {
            "overall_status": str,
            "risk_level": str,
            "dimensions": dict[str, str],
            "suggestions": list[str],
        }
    """
    if not summary:
        return {"overall_status": "", "risk_level": "", "dimensions": {}, "suggestions": []}

    # ---- 总体状态 ----
    overall_status = ""
    for label, kws in _STATUS_KEYWORDS:
        if any(k in summary for k in kws):
            overall_status = label
            break

    # ---- 风险 ----
    # 优先识别"未发现紧急风险"（含否定语境如"无自杀/自伤意念"）
    risk_level = ""
    if any(k in summary for k in _RISK_NONE):
        risk_level = "未发现紧急风险"
    elif any(k in summary for k in _RISK_HIGH):
        risk_level = "高风险"
    else:
        risk_level = "未发现紧急风险"

    # ---- 分维度（【情绪】xxx / **情绪**：xxx / - **情绪**：xxx / 情绪：xxx）----
    dimensions = {}
    # 先按行切分，逐行匹配（支持 markdown 列表项前缀 "- "）
    for line in summary.splitlines():
        line = line.strip()
        # 去掉 markdown 列表符号
        line2 = re.sub(r"^[-•·*]+\s*", "", line)
        m = re.match(
            r"(?:【([^】]+)】|\*\*([^*]+)\*\*|([\u4e00-\u9fa5]{2,6}))[：:]\s*(.+)",
            line2,
        )
        if not m:
            continue
        key = m.group(1) or m.group(2) or m.group(3)
        val = m.group(4).strip()
        if not key or not val:
            continue
        # 过滤非维度行（如"总体状态判断"）
        if any(x in key for x in ["总体", "风险", "免责", "建议", "总结", "分维度"]):
            continue
        # 过滤 value 里包含下一段标题的情况
        val = val.split("【")[0].split("**")[0].strip()
        dimensions[key] = val[:200]

    # 规范维度名映射（合并同义）
    DIM_ALIASES = {
        "情绪": "情绪", "情绪状态": "情绪", "心情": "情绪",
        "睡眠": "睡眠饮食", "睡眠饮食": "睡眠饮食", "饮食": "睡眠饮食", "胃口": "睡眠饮食",
        "认知": "认知思维", "认知思维": "认知思维", "思维": "认知思维", "想法": "认知思维",
        "社交": "社交人际", "社交人际": "社交人际", "人际": "社交人际",
        "压力": "压力应对", "压力应对": "压力应对", "工作压力": "压力应对",
    }
    normalized = {}
    for k, v in dimensions.items():
        key = DIM_ALIASES.get(k.strip(), k.strip())
        if key not in normalized:
            normalized[key] = v
    dimensions = normalized

    # ---- 建议（只在【具体建议】段落内匹配数字列表）----
    suggestions = []
    # 定位【具体建议】段落（支持 **【具体建议】** 或 【具体建议】）
    sug_section = re.search(
        r"(?:【|\*\*【)\s*具体建议\s*(?:】|\*\*】)\s*\n?(.*?)(?:\n\s*(?:【|\*\*【)\s*免责声明|$)",
        summary,
        re.S,
    )
    section = sug_section.group(1) if sug_section else ""
    if section:
        # 匹配 1. xxx / 2、xxx / 1）xxx（数字列表）
        sug_pattern = re.compile(r"(?:^|\n)\s*\d+[.、）)]\s*([^\n]+)")
        for m in sug_pattern.finditer(section):
            s = m.group(1).strip()
            if len(s) < 4:
                continue
            suggestions.append(s[:150])
    suggestions = suggestions[:5]

    return {
        "overall_status": overall_status,
        "risk_level": risk_level,
        "dimensions": dimensions,
        "suggestions": suggestions,
    }


async def save_assessment_record(
    db: AsyncSession,
    user_id: int,
    session_id: int,
    summary: str,
    turn_count: int = 0,
) -> AssessmentRecord | None:
    """保存一条评估记录（幂等：同一会话只保存一次）

    仅当回复包含结构化总结特征（【分维度概述】/【总体状态判断】等）时才落库，
    避免把开场白/中间轮次的问题误存为评估结果。
    """
    if not summary or len(summary) < 50:
        return None
    # 总结特征检测：必须出现总结标志（分维度概述 或 总体状态判断 或 总结）
    markers = ["分维度概述", "总体状态判断", "总体状态", "维度概述", "状态判断", "总结"]
    if not any(m in summary for m in markers):
        return None
    try:
        # 同一会话已有记录则跳过（避免重复保存）
        existing = (await db.execute(
            select(AssessmentRecord).where(
                AssessmentRecord.user_id == user_id,
                AssessmentRecord.session_id == session_id,
            )
        )).scalar_one_or_none()
        if existing:
            return existing

        parsed = parse_assessment_summary(summary)
        record = AssessmentRecord(
            user_id=user_id,
            session_id=session_id,
            overall_status=parsed["overall_status"],
            risk_level=parsed["risk_level"],
            dimensions_json=json.dumps(parsed["dimensions"], ensure_ascii=False),
            summary=summary[:5000],
            suggestions_json=json.dumps(parsed["suggestions"], ensure_ascii=False),
            turn_count=turn_count,
        )
        db.add(record)
        await db.flush()
        return record
    except Exception:
        return None


async def get_user_assessment_history(
    db: AsyncSession,
    user_id: int,
    limit: int = 5,
) -> list[dict]:
    """获取用户最近 N 次评估记录（最新在前）"""
    result = await db.execute(
        select(AssessmentRecord)
        .where(AssessmentRecord.user_id == user_id)
        .order_by(AssessmentRecord.created_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    out = []
    for r in records:
        try:
            dims = json.loads(r.dimensions_json or "{}")
        except Exception:
            dims = {}
        try:
            sugs = json.loads(r.suggestions_json or "[]")
        except Exception:
            sugs = []
        out.append({
            "id": r.id,
            "session_id": r.session_id,
            "overall_status": r.overall_status,
            "risk_level": r.risk_level,
            "dimensions": dims,
            "summary": r.summary,
            "suggestions": sugs,
            "turn_count": r.turn_count,
            "created_at": r.created_at.astimezone(CN_TZ).isoformat() if r.created_at else None,
        })
    return out


def build_personalized_context(records: list[dict], max_records: int = 3) -> str:
    """把历史评估记录转换为评估会话的个性化上下文（注入 system prompt）"""
    if not records:
        return ""
    parts = []
    for r in records[:max_records]:
        when = (r.get("created_at") or "")[:10]
        dims = r.get("dimensions") or {}
        dim_desc = "；".join(f"{k}: {v[:40]}" for k, v in dims.items()) or "（无）"
        parts.append(
            f"- {when} 评估：总体状态={r.get('overall_status') or '未知'}，"
            f"风险={r.get('risk_level') or '未知'}，维度：{dim_desc[:200]}"
        )
    return (
        "\n\n【用户历史评估档案（供参考，用于对比本次变化）】\n"
        + "\n".join(parts)
        + "\n请结合历史评估对比本次变化（如情绪是否好转/加重），并在总结时提及变化趋势。"
    )
