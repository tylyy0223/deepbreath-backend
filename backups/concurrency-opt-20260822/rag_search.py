"""Wiki.js 知识库搜索"""
import os, re, psycopg2, psycopg2.extras

from app.services.env import ensure_env  # 统一 env 加载，消除重复的 _load_env_fallback

ensure_env()

WIKI_BASE_URL = "https://luoyuyu.cn"

# 中文查询无空格分词，用常见分隔符拆分；英文按空格拆分
_SPLIT_RE = re.compile(r"[\s,，。.;；、!！?？:：'\"()（）\[\]【】]+")


def _tokenize(query: str) -> list[str]:
    """把查询拆成检索词：去标点 + 按分隔符切分 + 长句滑窗 + 过滤噪音

    策略：分隔符切出的每个块整体保留（如"演讲焦虑"）；超过 8 字的无分隔长块
    再拆 3-4 字滑窗（如"如何克服演讲焦虑" → 演讲焦虑/如何克服/克服演讲），
    滑窗片段只过滤明显噪音，不做严格停用词剔除（避免把关键词一起删掉）。
    """
    tokens = []
    for part in _SPLIT_RE.split(query):
        part = part.strip()
        if not part:
            continue
        if len(part) >= 6:
            # 无分隔符长句（≥6 字）：整块 + 4 字滑窗 + 3 字滑窗（中文关键词多为 2-4 字）
            tokens.append(part)
            for i in range(0, len(part) - 3):
                tokens.append(part[i : i + 4])
            for i in range(0, len(part) - 2):
                tokens.append(part[i : i + 3])
        else:
            tokens.append(part)
    # 过滤明显噪音（单字、无意义词；滑窗片段放宽）
    stop = {"我", "你", "他", "她", "它", "的", "了", "吗", "呢", "啊", "是", "在", "想", "什么", "这个", "那个", "一下", "一个", "最近", "请问", "帮我"}
    hard_stop = {"如何", "怎么", "克服", "了解", "我想", "我最近", "最近很", "情绪管理"}
    seen = set()
    out = []
    for t in tokens:
        if len(t) < 2 or t in stop:
            continue
        # 滑窗片段里若仅含"如何/克服"这类词且无实义词，丢弃
        if len(t) <= 4 and t in hard_stop:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    # 排序策略：4 字词最前（title 匹配主力），>6 字整块放最后（title 不会完整出现）
    out.sort(key=lambda t: (0 if len(t) == 4 else 1 if len(t) <= 6 else 2, -len(t)))
    # 限制关键词数量（防止 OR 子句与 score 表达式过度膨胀）
    return out[:6]


def _build_like_conditions(tokens: list[str], columns: list[str]) -> tuple[str, list]:
    """构造 OR ILIKE 条件，返回 (sql_fragment, params)"""
    clauses = []
    params = []
    for t in tokens:
        p = f"%{t}%"
        for col in columns:
            clauses.append(f"{col} ILIKE %s")
            params.append(p)
    return " OR ".join(clauses), params


def search_wiki(query, limit=5):
    """在 v_psy_chat_pages 视图中搜索

    两级检索：
    1. 快速层：仅 title + description 匹配（<10ms，标题已含核心主题）
    2. 兜底层：结果不足时回退 title + content 匹配（慢，但保证召回）
    """
    rows = []
    tokens = _tokenize(query)
    if not tokens:
        return {"results": [], "total": 0, "query": query}

    def _query(tk: list, columns: list[str], lim: int):
        # 去重列（title 匹配时避免重复 OR 条件）
        uniq_cols = list(dict.fromkeys(columns))
        cond, _cond_params = _build_like_conditions(tk, uniq_cols)
        score_col = "content" if "content" in uniq_cols else uniq_cols[0]
        score_expr = " + ".join(
            f"(CASE WHEN title ILIKE %s THEN 2 ELSE 0 END + CASE WHEN {score_col} ILIKE %s THEN 1 ELSE 0 END)"
            for _ in tk
        )
        # 参数顺序必须与 SQL 文本一致：SELECT 的 score_expr → WHERE 的 cond → LIMIT
        params = []
        for t in tk:
            params.extend([f"%{t}%", f"%{t}%"])
        params.extend(_cond_params)
        params.append(lim)
        sql = f"""
            SELECT id, title, description,
                   LEFT(content, 800) AS content_preview,
                   path, "localeCode", tree_title,
                   ({score_expr}) AS score
            FROM v_psy_chat_pages
            WHERE {cond}
            ORDER BY score DESC, LENGTH(content) ASC
            LIMIT %s
        """
        return sql, params

    try:
        conn = psycopg2.connect(
            host=os.environ.get("WIKI_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("WIKI_DB_PORT", "5432")),
            dbname=os.environ.get("WIKI_DB_NAME", "wikijs"),
            user=os.environ.get("WIKI_DB_USER", "deepbreath_wiki_reader"),
            password=os.environ.get("WIKI_DB_PASSWORD", ""),
            connect_timeout=3,
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 第一级：仅 title 匹配（title 列小，全 token OR 也快；覆盖核心词）
        sql, params = _query(tokens, ["title", "title"], limit)
        cur.execute(sql, params)
        rows = cur.fetchall()

        # 第二级：不足 limit 时，回退 title + content（覆盖正文命中；
        # content 列大，单 token 扫描恒定 ~2.3s，用最强 token 一次补齐）
        if len(rows) < limit:
            content_tokens = tokens[:1]
            sql, params = _query(content_tokens, ["title", "content"], limit)
            cur.execute(sql, params)
            extra = cur.fetchall()
            seen_ids = {r["id"] for r in rows}
            for r in extra:
                if r["id"] not in seen_ids:
                    rows.append(r)
                if len(rows) >= limit:
                    break

        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e), "results": [], "total": 0, "query": query}

    results = []
    seen_titles = set()
    for row in rows[:limit]:
        title = row["title"] or ""
        if title in seen_titles:
            continue
        seen_titles.add(title)
        content = row.get("content_preview") or ""
        clean = re.sub(r"<[^>]+>", "", content)[:600]
        path = row.get("path") or ""
        locale = row.get("localeCode") or "zh"
        page_url = f"{WIKI_BASE_URL}/{locale}/{path}" if path else ""
        results.append({
            "title": title, "path": path, "page_url": page_url,
            "description": row.get("description") or "", "content": clean,
        })
    return {"results": results, "total": len(results), "query": query}
