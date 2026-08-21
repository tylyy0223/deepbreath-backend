"""Wiki.js 知识库搜索"""
import os, re, psycopg2, psycopg2.extras

from app.services.env import ensure_env  # 统一 env 加载，消除重复的 _load_env_fallback

ensure_env()

WIKI_BASE_URL = "https://luoyuyu.cn"


def search_wiki(query, limit=5):
    """在 v_psy_chat_pages 视图中搜索"""
    rows = []
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
        sql = """
            SELECT id, title, description,
                   LEFT(content, 800) AS content_preview,
                   path, "localeCode", tree_title
            FROM v_psy_chat_pages
            WHERE title ILIKE %s OR content ILIKE %s
            ORDER BY
                CASE WHEN title ILIKE %s THEN 0 ELSE 1 END,
                LENGTH(content) ASC
            LIMIT %s
        """
        pattern = "%" + query + "%"
        cur.execute(sql, (pattern, pattern, pattern, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e), "results": [], "total": 0}

    results = []
    seen_titles = set()
    for row in rows:
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
    return {"results": results, "total": len(results)}
