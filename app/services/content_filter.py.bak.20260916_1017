"""内容安全过滤 — 敏感词检测 + 自动替换/拦截"""
import re

# 需要拦截的敏感词（匹配则拒绝发布）
BLOCK_WORDS = [
    # 广告/营销
    "加微信", "加我微信", "微信号", "扫码加", "免费咨询",
    "收费", "价格", "付款", "转账", "代购",
    # 政治敏感
    "自杀方法", "如何自杀", "怎么死", "自残方法",
    # 色情
    "约炮", "一夜情",
]

# 需要替换为安全词汇的
REPLACE_MAP = {
    "心理治疗": "心理科普",
    "心理医生": "心理咨询师",
    "精神科": "心理健康",
    "抑郁症诊断": "情绪状态",
    "药物治疗": "专业帮助",
    "开药": "就医建议",
    "处方药": "专业建议",
    "治病": "调整状态",
    "精神病": "心理健康问题",
}


def check_content(text: str) -> tuple[bool, str]:
    """检查文本是否包含敏感内容。
    Returns: (is_safe, filtered_text_or_error)
    """
    # 1. 检查拦截词
    for word in BLOCK_WORDS:
        if word in text:
            return False, f"内容包含不当词汇，请修改后重新发布"

    # 2. 替换敏感词
    filtered = text
    for old, new in REPLACE_MAP.items():
        filtered = filtered.replace(old, new)

    # 3. 检查联系电话（11 位手机号、座机号）
    if re.search(r"1[3-9]\d{9}", filtered):
        return False, "请勿发布手机号码"

    # 4. 检查 URL
    if re.search(r"https?://|www\.", filtered):
        return False, "请勿发布外部链接"

    return True, filtered
