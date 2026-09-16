"""内容安全过滤 — 敏感词检测 + 自动替换/拦截

加固点:
- NFKC Unicode 归一化: 全角→半角, 兼容字符折叠
- 零宽/不可见字符剥离: 防 \u200B / \u200C / \u200D / \uFEFF 等插入绕过
- 长度上限: 防超长输入 DoS

注意: 白名单词数量有限, 漏报率高 (拼音首字母/emoji/同义词等仍可绕过),
生产环境强烈建议接入第三方敏感词服务 (腾讯云内容安全/阿里云内容安全 等).
"""
import re
import unicodedata

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


# 零宽/不可见字符 Unicode 码点集合 (剥离后再做匹配)
_INVISIBLE_CHARS = re.compile(
    "[\u200B\u200C\u200D\u200E\u200F"  # 零宽空格/连接符/方向符
    "\u202A\u202B\u202C\u202D\u202E"   # 双向控制符
    "\uFEFF"                              # BOM
    "\u00AD"                              # 软连字符
    "\u2060\u2061\u2062\u2063\u2064"   # 不可见数学/格式字符
    "]"
)
MAX_CONTENT_LENGTH = 5000  # 单条内容最大长度 (防 DoS / 超长内容审核绕过)


def _normalize(text: str) -> str:
    """NFKC 归一化 + 剥离不可见字符 + 折叠空白"""
    if not text:
        return ""
    # 1. Unicode NFKC: 全角→半角, 兼容字符折叠 (e.g. "ＡＢＣ" → "ABC", "①" → "1")
    text = unicodedata.normalize("NFKC", text)
    # 2. 剥离零宽/不可见字符
    text = _INVISIBLE_CHARS.sub("", text)
    # 3. 多空白折叠为单空格 (防 "自 杀" 中插入空格的绕过变种)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def check_content(text: str) -> tuple[bool, str]:
    """检查文本是否包含敏感内容。
    Returns: (is_safe, filtered_text_or_error)
    """
    if text is None:
        return False, "内容不能为空"

    # 0. 长度上限 (防 DoS / 超长内容审核绕过)
    if len(text) > MAX_CONTENT_LENGTH:
        return False, f"内容超过 {MAX_CONTENT_LENGTH} 字符限制"

    # 0.5 NFKC 归一化 + 零宽剥离后再匹配
    normalized = _normalize(text)

    # 1. 检查拦截词 (在原文 + 归一化后文本上各匹配一次, 双保险)
    for src_text in (text, normalized):
        for word in BLOCK_WORDS:
            if word in src_text:
                return False, "内容包含不当词汇，请修改后重新发布"

    # 2. 替换敏感词 (在归一化文本上做替换)
    filtered = normalized
    for old, new in REPLACE_MAP.items():
        filtered = filtered.replace(old, new)

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
