"""心理学自评量表定义 — SDS / SAS / SCL-90"""

# ---------- 量表配置 ----------

SCALES = {
    "sds": {
        "id": "sds",
        "name": "抑郁自评量表",
        "name_en": "SDS",
        "emoji": "😔",
        "description": "Zung 抑郁自评量表，用于评估抑郁程度",
        "time_estimate": "约3-5分钟",
        "questions_count": 20,
        "max_score": 80,
        "score_fn": "sds_score",
    },
    "sas": {
        "id": "sas",
        "name": "焦虑自评量表",
        "name_en": "SAS",
        "emoji": "😰",
        "description": "Zung 焦虑自评量表，用于评估焦虑程度",
        "time_estimate": "约3-5分钟",
        "questions_count": 20,
        "max_score": 80,
        "score_fn": "sas_score",
    },
    "scl90": {
        "id": "scl90",
        "name": "症状自评量表",
        "name_en": "SCL-90",
        "emoji": "📋",
        "description": "90项症状清单，评估10个维度的心理健康状况",
        "time_estimate": "约15-20分钟",
        "questions_count": 90,
        "max_score": 450,
        "score_fn": "scl90_score",
    },
}

# 4级评分选项
LIKERT_4 = [
    {"value": 1, "label": "没有或很少时间"},
    {"value": 2, "label": "少部分时间"},
    {"value": 3, "label": "相当多时间"},
    {"value": 4, "label": "绝大部分或全部时间"},
]

# 5级评分选项
LIKERT_5 = [
    {"value": 1, "label": "没有"},
    {"value": 2, "label": "很轻"},
    {"value": 3, "label": "中等"},
    {"value": 4, "label": "偏重"},
    {"value": 5, "label": "严重"},
]

# ---------- SDS 量表 ----------
# 20题，4级评分。10题反向计分：2,5,6,11,12,14,16,17,18,20
SDS_QUESTIONS = [
    # (序号, 题目, 是否反向计分)
    # 正向计分
    (1, "我觉得闷闷不乐，情绪低沉", False),
    (2, "我觉得一天之中早晨最好", True),
    (3, "我一阵阵哭出来或觉得想哭", False),
    (4, "我晚上睡眠不好", False),
    (5, "我吃得跟平常一样多", True),
    (6, "我与异性密切接触时和以往一样感到愉快", True),
    (7, "我发觉我的体重在下降", False),
    (8, "我有便秘的苦恼", False),
    (9, "我心跳比平时快", False),
    (10, "我无缘无故地感到疲乏", False),
    (11, "我的头脑跟平常一样清楚", True),
    (12, "我觉得经常做的事情并没有困难", True),
    (13, "我觉得不安而平静不下来", False),
    (14, "我对将来抱有希望", True),
    (15, "我比平常容易生气激动", False),
    (16, "我觉得作出决定是容易的", True),
    (17, "我觉得自己是个有用的人，有人需要我", True),
    (18, "我的生活过得很有意思", True),
    (19, "我认为如果我死了，别人会过得好些", False),
    (20, "我平常感兴趣的事我仍然感兴趣", True),
]

SDS_RESULT_TABLE = [
    (0, 49, "正常", "你的抑郁评分在正常范围内，说明近期情绪状态良好。请继续保持健康的生活方式。"),
    (50, 59, "轻度抑郁", "有轻度的抑郁倾向。建议关注自己的情绪变化，适当增加运动和社交活动，必要时可寻求心理咨询。"),
    (60, 69, "中度抑郁", "有明显的抑郁症状。建议尽早寻求专业心理咨询或精神科医生的帮助，进行进一步评估。"),
    (70, 100, "重度抑郁", "有严重的抑郁症状。请尽快寻求专业医疗机构的帮助，及时进行诊断和治疗。"),
]


# ---------- SAS 量表 ----------
# 20题，4级评分。5题反向计分：5,9,13,17,19
SAS_QUESTIONS = [
    (1, "我觉得比平常容易紧张和着急", False),
    (2, "我无缘无故地感到害怕", False),
    (3, "我容易心里烦乱或觉得惊恐", False),
    (4, "我觉得我可能将要发疯", False),
    (5, "我觉得一切都很好，也不会发生什么不幸", True),
    (6, "我手脚发抖打颤", False),
    (7, "我因为头痛、颈痛和背痛而苦恼", False),
    (8, "我感觉容易衰弱和疲乏", False),
    (9, "我觉得心平气和，并且容易安静坐着", True),
    (10, "我觉得心跳得很快", False),
    (11, "我因为一阵阵头晕而苦恼", False),
    (12, "我有过晕倒发作，或觉得要晕倒似的", False),
    (13, "我吸气呼气都感到很容易", True),
    (14, "我的手脚麻木和刺痛", False),
    (15, "我因为胃痛和消化不良而苦恼", False),
    (16, "我常常要小便", False),
    (17, "我的手脚常常是干燥温暖的", True),
    (18, "我脸红发热", False),
    (19, "我容易入睡并且一夜睡得很好", True),
    (20, "我做噩梦", False),
]

SAS_RESULT_TABLE = [
    (0, 49, "正常", "你的焦虑评分在正常范围内，说明近期焦虑水平较低。"),
    (50, 59, "轻度焦虑", "有轻度的焦虑倾向。建议学习一些放松技巧，如深呼吸、正念冥想等。"),
    (60, 69, "中度焦虑", "有明显的焦虑症状。建议寻求专业心理咨询或精神科医生的评估。"),
    (70, 100, "重度焦虑", "有重度焦虑症状。请尽快寻求专业医疗机构的帮助。"),
]


# ---------- SCL-90 量表 ----------
# 90题，5级评分。10个维度
SCL90_DIMENSIONS = [
    {"name": "躯体化", "name_en": "Somatization", "items": [1,4,12,27,40,42,48,49,52,53,56,58], "icon": "🏥"},
    {"name": "强迫症状", "name_en": "Obsessive-Compulsive", "items": [3,9,10,28,38,45,46,51,55,65], "icon": "🔄"},
    {"name": "人际关系敏感", "name_en": "Interpersonal Sensitivity", "items": [6,21,34,36,37,41,61,69,73], "icon": "👥"},
    {"name": "抑郁", "name_en": "Depression", "items": [5,14,15,20,22,26,29,30,31,32,54,71,79], "icon": "😔"},
    {"name": "焦虑", "name_en": "Anxiety", "items": [2,17,23,33,39,57,72,78,80,86], "icon": "😰"},
    {"name": "敌对", "name_en": "Hostility", "items": [11,24,63,67,74,81], "icon": "😠"},
    {"name": "恐怖", "name_en": "Phobic Anxiety", "items": [13,25,47,50,70,75,82], "icon": "😨"},
    {"name": "偏执", "name_en": "Paranoid Ideation", "items": [8,18,43,68,76,83], "icon": "🕵️"},
    {"name": "精神病性", "name_en": "Psychoticism", "items": [7,16,35,62,77,84,85,87,88,90], "icon": "🧩"},
    {"name": "其他", "name_en": "Additional", "items": [19,44,59,60,64,66,89], "icon": "📌"},
]

SCL90_QUESTIONS = [
    (1, "头痛"),
    (2, "神经过敏，心中不踏实"),
    (3, "头脑中有不必要的想法或字句盘旋"),
    (4, "头昏或昏倒"),
    (5, "对异性的兴趣减退"),
    (6, "对旁人责备求全"),
    (7, "感到别人能控制您的思想"),
    (8, "责怪别人制造麻烦"),
    (9, "忘性大"),
    (10, "担心自己的衣饰整齐及仪态的端正"),
    (11, "容易烦恼和激动"),
    (12, "胸痛"),
    (13, "害怕空旷的场所或街道"),
    (14, "感到自己的精力下降，活动减慢"),
    (15, "想结束自己的生命"),
    (16, "听到旁人听不到的声音"),
    (17, "发抖"),
    (18, "感到大多数人都不可信任"),
    (19, "胃口不好"),
    (20, "容易哭泣"),
    (21, "同异性相处时感到害羞不自在"),
    (22, "感到受骗，中了圈套或有人想抓住您"),
    (23, "无缘无故地突然感到害怕"),
    (24, "自己不能控制地大发脾气"),
    (25, "怕单独出门"),
    (26, "经常责怪自己"),
    (27, "腰痛"),
    (28, "感到难以完成任务"),
    (29, "感到孤独"),
    (30, "感到苦闷"),
    (31, "过分担忧"),
    (32, "对事物不感兴趣"),
    (33, "感到害怕"),
    (34, "感情容易受到伤害"),
    (35, "感到别人能知道您的私下想法"),
    (36, "感到别人不理解您不同情您"),
    (37, "感到人们对您不太友好"),
    (38, "做事必须做得很慢以保证做得正确"),
    (39, "心跳得很厉害"),
    (40, "恶心或胃部不舒服"),
    (41, "感到比不上他人"),
    (42, "肌肉酸痛"),
    (43, "感到有人在监视您谈论您"),
    (44, "难以入睡"),
    (45, "做事必须反复检查"),
    (46, "难以做出决定"),
    (47, "怕乘电车、公共汽车、地铁或火车"),
    (48, "呼吸有困难"),
    (49, "一阵阵发冷或发热"),
    (50, "因为感到害怕而避开某些事"),
    (51, "脑子变空了"),
    (52, "身体发麻或刺痛"),
    (53, "喉咙有梗塞感"),
    (54, "感到没有前途没有希望"),
    (55, "不能集中注意力"),
    (56, "感到身体的某一部分软弱无力"),
    (57, "感到紧张或容易紧张"),
    (58, "感到手或脚发重"),
    (59, "想到死亡的事情"),
    (60, "吃得太多"),
    (61, "当别人看着您或谈论您时感到不自在"),
    (62, "有一些不属于您自己的想法"),
    (63, "有想打人或伤害他人的冲动"),
    (64, "醒得太早"),
    (65, "必须反复洗手、点数目或触摸某些东西"),
    (66, "睡得不稳不深"),
    (67, "有想摔坏或破坏东西的冲动"),
    (68, "有一些别人没有的想法或念头"),
    (69, "感到对别人神经过敏"),
    (70, "在商店或电影院等人多的地方感到不自在"),
    (71, "感到做任何事情都很困难"),
    (72, "一阵阵恐惧或惊恐"),
    (73, "感到在公共场合吃东西很不舒服"),
    (74, "经常与人争论"),
    (75, "单独一人时神经很紧张"),
    (76, "别人对您的成绩没有做出恰当的评价"),
    (77, "即使和别人在一起也感到孤单"),
    (78, "感到坐立不安心神不定"),
    (79, "感到自己没有什么价值"),
    (80, "感到熟悉的东西变得陌生或不像是真的"),
    (81, "大叫或摔东西"),
    (82, "害怕会在公共场合昏倒"),
    (83, "感到别人想占您的便宜"),
    (84, "为一些有关性的想法而苦恼"),
    (85, "您认为应该因为自己的过错而受到惩罚"),
    (86, "感到要很快把事情做完"),
    (87, "感到自己的身体有严重问题"),
    (88, "从未感到和其他人很亲近"),
    (89, "感到自己有罪"),
    (90, "感到自己的脑子有毛病"),
]

SCL90_RESULT_TABLE = [
    (0, 1.5, "正常", "各维度评分均在正常范围内，心理健康状况良好。"),
    (1.5, 2.0, "轻度异常", "部分维度评分略有偏高，建议关注相关方面的状态变化。"),
    (2.0, 3.0, "中度异常", "多个维度评分偏高，建议寻求专业心理健康评估。"),
    (3.0, 5.0, "重度异常", "多个维度评分明显偏高，请尽快寻求专业医疗机构的帮助。"),
]


# ---------- 计分函数 ----------

def calc_sds_score(answers: dict) -> dict:
    """计算 SDS 得分 answers: {question_idx: value}"""
    raw = 0
    for idx, (qnum, _, reversed_) in enumerate(SDS_QUESTIONS):
        val = answers.get(f"q{qnum}", 3)  # default center
        if reversed_:
            val = 5 - val  # 1→4, 2→3, 3→2, 4→1
        raw += val
    # 粗分 × 1.25 = 标准分
    std = raw * 1.25
    std = round(std, 1)
    # 解释
    level_name, level_desc = "正常", ""
    for lo, hi, name, desc in SDS_RESULT_TABLE:
        if lo <= std <= hi:
            level_name = name
            level_desc = desc
            break
    return {
        "raw_score": raw,
        "standard_score": std,
        "level": level_name,
        "description": level_desc,
        "max_raw": 80,
    }


def calc_sas_score(answers: dict) -> dict:
    """计算 SAS 得分"""
    raw = 0
    for idx, (qnum, _, reversed_) in enumerate(SAS_QUESTIONS):
        val = answers.get(f"q{qnum}", 3)
        if reversed_:
            val = 5 - val
        raw += val
    std = round(raw * 1.25, 1)
    level_name, level_desc = "正常", ""
    for lo, hi, name, desc in SAS_RESULT_TABLE:
        if lo <= std <= hi:
            level_name = name
            level_desc = desc
            break
    return {
        "raw_score": raw,
        "standard_score": std,
        "level": level_name,
        "description": level_desc,
        "max_raw": 80,
    }


def calc_scl90_score(answers: dict) -> dict:
    """计算 SCL-90 各维度得分"""
    dimension_scores = []
    total = 0
    total_items = 0
    for dim in SCL90_DIMENSIONS:
        dim_sum = 0
        dim_count = 0
        for item_num in dim["items"]:
            val = answers.get(f"q{item_num}", 1)
            dim_sum += val
            dim_count += 1
        dim_avg = round(dim_sum / dim_count, 2) if dim_count > 0 else 0
        total += dim_sum
        total_items += dim_count
        dimension_scores.append({
            "name": dim["name"],
            "icon": dim["icon"],
            "score": dim_sum,
            "avg": dim_avg,
            "item_count": dim_count,
        })

    gsi = round(total / total_items, 2) if total_items > 0 else 0
    # 阳性症状均分 (PSD) = 阳性项目总分 / 阳性项目数（评分≥2的项目）
    positive_sum = 0
    positive_count = 0
    for k, v in answers.items():
        if v >= 2:
            positive_sum += v
            positive_count += 1
    psd = round(positive_sum / positive_count, 2) if positive_count > 0 else 0
    # 阳性项目数
    pst = positive_count  # Positive Symptom Total

    # 总体评价
    level_name, level_desc = "正常", ""
    for lo, hi, name, desc in SCL90_RESULT_TABLE:
        if lo <= gsi <= hi:
            level_name = name
            level_desc = desc
            break

    return {
        "gsi": gsi,
        "pst": pst,
        "psd": psd,
        "dimensions": dimension_scores,
        "level": level_name,
        "description": level_desc,
        "total_raw": total,
        "max_raw": 450,
    }


# 按维度标记高亮（avg >= 2 为偏高）
def get_scl90_highlights(result: dict) -> list:
    """返回 SCL-90 评分偏高的维度列表"""
    highlights = []
    for d in result["dimensions"]:
        if d["avg"] >= 2.0:
            highlights.append(d)
    return highlights
