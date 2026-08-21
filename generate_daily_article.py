"""每日自动生成一篇心理学专业文章，直接写入 articles 表。

部署方式（服务器上）：
  crontab -e
  0 7 * * * cd /root/deep-breath/backend && venv/bin/python generate_daily_article.py >> /var/log/deepbreath_cron.log 2>&1
（每天早上 7 点执行，日志写入 /var/log/deepbreath_cron.log）

调用 DeepSeek V4 → 生成 Markdown 长文 → 写入 PostgreSQL。
"""
import json, os, random, sys, time, traceback
from datetime import datetime, timezone, timedelta

import httpx
import psycopg2
import psycopg2.extras

# ==== 配置（从环境变量读取，systemd EnvironmentFile 会在 cron 继承不到；此处兜底读 .env）====
def _load_env():
    env = {}
    env_file = "/root/deep-breath/backend/.env"
    if os.path.exists(env_file):
        for line in open(env_file, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

ENV = _load_env()
DEEPSEEK_API_KEY = ENV.get("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
DEEPSEEK_BASE_URL = ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DB_NAME = ENV.get("DB_NAME", "deepbreath")
DB_USER = ENV.get("DB_USER", "deepbreath")
DB_PASSWORD = ENV.get("DB_PASSWORD", "")
DB_HOST = ENV.get("DB_HOST", "127.0.0.1")
DB_PORT = int(ENV.get("DB_PORT", "5432"))
CST = timezone(timedelta(hours=8))  # 北京时间

# ==== 话题库（每天随机抽一个，避免重复感）====
TOPICS = [
    {"category_slug": "stress-relief", "area": "压力管理",
     "prompt": "写一篇关于「职场压力与心理韧性」的心理学专业文章。包含：压力的生理机制（皮质醇、交感神经）、心理韧性(resilience)的定义与可训练性、3个实证支持的应对策略（如认知重评、社会支持、正念）。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "positive-growth", "area": "积极心理学",
     "prompt": "写一篇关于「心流体验(Flow)与幸福感」的心理学专业文章。包含：心流的定义（Csikszentmihalyi理论）、进入心流的条件（挑战-技能平衡、明确目标、即时反馈）、日常生活中的心流实践方法。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "low-mood", "area": "情绪调节",
     "prompt": "写一篇关于「情绪调节策略」的心理学专业文章。包含：情绪调节的Gross过程模型（情境选择→注意部署→认知改变→反应调整）、适应性策略vs非适应性策略的对比、3个日常可操作的情绪调节技巧。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "stress-relief", "area": "睡眠心理",
     "prompt": "写一篇关于「睡眠与心理健康」的心理学专业文章。包含：睡眠阶段与大脑修复机制、失眠的认知行为模型（3P模型）、CBT-I（失眠认知行为治疗）的核心方法与实证效果。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "positive-growth", "area": "人际关系",
     "prompt": "写一篇关于「依恋理论与人际关系」的心理学专业文章。包含：依恋理论的起源（Bowlby & Ainsworth）、四种依恋类型及其成人表现、如何通过自我觉察改善不安全依恋。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "stress-relief", "area": "认知偏差",
     "prompt": "写一篇关于「认知偏差与日常决策」的心理学专业文章。包含：Daniel Kahneman的双系统理论、3-4种常见认知偏差（确认偏误、可得性启发、损失厌恶等）及其实例、如何通过元认知训练减少偏差影响。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "low-mood", "area": "自我关怀",
     "prompt": "写一篇关于「自我关怀(Self-Compassion)」的心理学专业文章。包含：Kristin Neff的自我关怀三要素（自我友善、共同人性、正念觉察）、自我关怀vs自尊的区别、3个实证支持的自我关怀练习。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "positive-growth", "area": "动机心理",
     "prompt": '写一篇关于内在动机与外在动机的心理学专业文章。包含：自我决定理论(SDT)的三大基本需求(自主性、胜任感、关系需求)、外在奖励对内在动机的挤出效应、如何在工作和学习中培养内在动机。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。'},
    {"category_slug": "stress-relief", "area": "习惯形成",
     "prompt": "写一篇关于「习惯形成的心理学机制」的心理学专业文章。包含：习惯循环（提示→惯常行为→奖励）、Duhigg和Clear的习惯理论、基于行为心理学的习惯改变策略（执行意图、环境设计、微习惯法）。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "positive-growth", "area": "正念冥想",
     "prompt": "写一篇关于「正念冥想(Mindfulness)的神经科学基础」的心理学专业文章。包含：正念的定义与传统来源、关键脑区变化（前额叶增厚、杏仁核缩小）的fMRI研究证据、MBSR/MBCT等主流正念干预方案及效果数据。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "low-mood", "area": "社会支持",
     "prompt": "写一篇关于「社会支持与心理健康」的心理学专业文章。包含：社会支持的四种类型（情感、工具、信息、评价）、社会支持缓冲压力假说、孤独感的健康影响及其缓解策略。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
    {"category_slug": "positive-growth", "area": "心理灵活",
     "prompt": "写一篇关于「心理灵活性(Psychological Flexibility)」的心理学专业文章。包含：ACT接纳承诺疗法的六边形模型、心理灵活性vs经验性回避、日常生活中培养心理灵活性的ACT练习。800-1200字，Markdown格式，至少包含两个##子标题。语言专业但通俗，适合普通读者。"},
]


def generate_article(topic: dict) -> dict | None:
    """调用 DeepSeek V4 生成文章，返回 {title,summary,content}"""
    system = (
        "你是一位资深的心理学研究者与科普作家。请根据用户指定的话题，撰写一篇高质量、"
        "有深度的心理学专业文章。要求：① 信息准确、有理论支撑；② 包含具体实例，"
        "③ 语言通俗但不失专业感，面向大众读者；"
        "④ 严格使用 Markdown 格式，用 ## 和 ### 分层，必要时用列表。"
        "⑤ 文章最后附一段扩展阅读推荐（1-2 本相关书籍）。"
    )
    try:
        resp = httpx.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-v4-flash", "temperature": 0.6,
                  "messages": [
                      {"role": "system", "content": system},
                      {"role": "user", "content": topic["prompt"]},
                  ]},
            timeout=180,
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"] if data.get("choices") else ""
    except Exception:
        traceback.print_exc()
        return None

    content = content.strip()
    if not content or len(content) < 400:
        print("⚠️  生成内容过短，放弃")
        return None

    # 提取标题（第一篇 ## 后的文本）
    title = topic["area"]
    for line in content.split("\n"):
        if line.startswith("## "):
            t = line[3:].strip()
            if len(t) >= 4:
                title = t
                break

    # 摘要（取正文前 120 字，去掉标题和符号）
    clean = content.replace("#", "").replace("*", "").strip()
    summary = clean[:120] + "…" if len(clean) > 120 else clean

    return {"title": title, "summary": summary, "content": content,
            "category_slug": topic["category_slug"], "area": topic["area"]}


def save_article(art: dict):
    """直接写入 PostgreSQL articles 表"""
    slug_base = art["area"].replace(" ", "-")[:30]
    slug = f"daily-{slug_base}-{datetime.now(CST).strftime('%Y%m%d')}"
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # 查分类 ID
        cur.execute("SELECT id FROM categories WHERE slug = %s", (art["category_slug"],))
        row = cur.fetchone()
        if not row:
            # fallback：用第一个分类
            cur.execute("SELECT id, slug FROM categories WHERE status = 'active' ORDER BY id LIMIT 1")
            row = cur.fetchone()
        cat_id = row["id"]

        cur.execute("""
            INSERT INTO articles (title, slug, summary, content, cover_url, view_count, category_id, status, is_featured, published_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, '', 0, %s, 'published', TRUE, %s, %s, %s)
            ON CONFLICT (slug) DO NOTHING
            RETURNING id
        """, (art["title"], slug, art["summary"], art["content"], cat_id,
              datetime.now(CST), datetime.now(CST), datetime.now(CST)))
        result = cur.fetchone()
        conn.commit()
        if result:
            print(f"✅ 已发布: 《{art['title']}》 (id={result['id']}, slug={slug})")
        else:
            print(f"⚠️  今天已有同名文章，跳过: {slug}")
    except Exception:
        conn.rollback()
        traceback.print_exc()
    finally:
        conn.close()


# ==== 话题使用历史（避免短期内重复）====
HISTORY_FILE = "/root/deep-breath/backend/daily_article_history.json"
HISTORY_DAYS = len(TOPICS)  # 轮转窗口 = 话题总数，保证全部轮过一遍才重复


def _load_history() -> list[dict]:
    """加载历史记录 [{area, date}, ...]"""
    if os.path.exists(HISTORY_FILE):
        try:
            return json.load(open(HISTORY_FILE, "r", encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_history(history: list[dict]):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def pick_topic() -> dict:
    """选择一个话题，排除最近 HISTORY_DAYS 天内已用过的"""
    history = _load_history()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")
    recent_areas = {h["area"] for h in history if h.get("date", "") >= cutoff}
    # 过滤掉最近用过的
    candidates = [t for t in TOPICS if t["area"] not in recent_areas]
    if not candidates:
        # 全部都用过了，重置（从最早的开始排）
        candidates = TOPICS
        print("🔄 所有话题已轮转一遍，重新开始")
    chosen = random.choice(candidates)
    return chosen


def record_topic(area: str):
    """记录话题使用"""
    history = _load_history()
    history.append({"area": area, "date": datetime.now(timezone.utc).strftime("%Y%m%d")})
    # 只保留最近 60 条
    _save_history(history[-60:])


def main():
    if not DEEPSEEK_API_KEY:
        print("❌ DEEPSEEK_API_KEY 未配置"); sys.exit(1)

    topic = pick_topic()
    print(f"\n{'='*50}")
    print(f"📝 {datetime.now(timezone.utc).isoformat()}  话题: {topic['area']}")
    art = generate_article(topic)
    if art is None:
        print("❌ 生成失败")
        sys.exit(1)
    save_article(art)
    record_topic(topic["area"])
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
