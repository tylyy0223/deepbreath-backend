"""参考文献 API — 从 Wiki.js 数据库提取心理学电子书书目"""
import os
import re
from fastapi import APIRouter
import psycopg2
import psycopg2.extras

router = APIRouter(prefix="/api/v1/references", tags=["参考文献"])

WIKI_BASE_URL = "https://luoyuyu.cn"
WIKI_DB = {
    "host": os.environ.get("WIKI_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("WIKI_DB_PORT", "5432")),
    "dbname": os.environ.get("WIKI_DB_NAME", "wikijs"),
    "user": os.environ.get("WIKI_DB_USER", "deepbreath_wiki_reader"),
    "password": os.environ.get("WIKI_DB_PASSWORD", ""),
}

_SEG_PREFIX = re.compile(r"^004-\d{3}[-\s]*")
_SUB_SERIAL = re.compile(r"^\d{3}(?=[一-鿿])")  # 嵌套子编号（后跟中文才剥离，保护「50个…」「5%…」这类书名）
_SERIAL_RE = re.compile(r"^004-(\d{3})")


def _connect():
    return psycopg2.connect(**WIKI_DB, connect_timeout=3)


def find_book_by_serial(serial: str) -> dict | None:
    """按 Wiki 编号（如 '042'）查书：返回 {name, author, seg, chapters} 或 None"""
    serial = serial.zfill(3)
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT split_part(path, '/', 2) AS seg, COUNT(*) AS chapters
            FROM v_psy_chat_pages
            WHERE split_part(path, '/', 2) LIKE %s
              AND title IS NOT NULL AND title != ''
            GROUP BY seg LIMIT 1
        """, (f"004-{serial}%",))
        row = cur.fetchone()
        cur.close()
        conn.close()
    except Exception:
        return None
    if not row:
        return None
    name, author = _parse_book(row["seg"])
    return {"name": name, "author": author, "seg": row["seg"], "chapters": int(row["chapters"])}


def get_book_excerpts(serial: str, query: str = "", limit: int = 8) -> list[dict]:
    """取某本书的章节内容片段（有 query 时书内检索，否则按章节顺序取开头几章）"""
    serial = serial.zfill(3)
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if query:
            cur.execute("""
                SELECT title, LEFT(content, 900) AS excerpt
                FROM v_psy_chat_pages
                WHERE split_part(path, '/', 2) LIKE %s
                  AND (title ILIKE %s OR content ILIKE %s)
                ORDER BY path LIMIT %s
            """, (f"004-{serial}%", f"%{query}%", f"%{query}%", limit))
        else:
            cur.execute("""
                SELECT title, LEFT(content, 900) AS excerpt
                FROM v_psy_chat_pages
                WHERE split_part(path, '/', 2) LIKE %s
                ORDER BY path LIMIT %s
            """, (f"004-{serial}%", limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception:
        return []
    out = []
    for r in rows:
        text = re.sub(r"<[^>]+>", "", r["excerpt"] or "").strip()
        if text:
            out.append({"title": r["title"] or "", "excerpt": text})
    return out


def _parse_book(seg: str) -> tuple[str, str]:
    """从路径段解析（书名, 作者）。如 '004-285 盲点-马扎林贝纳基 安东尼格林沃' → ('盲点', '马扎林贝纳基 安东尼格林沃')"""
    name = _SEG_PREFIX.sub("", seg).strip()
    name = _SUB_SERIAL.sub("", name).strip()
    author = ""
    # 「书名-作者」模式：后缀不含数字且较短时视为作者
    if "-" in name:
        head, _, tail = name.rpartition("-")
        if head and tail and len(tail) <= 20 and not re.search(r"\d", tail):
            name, author = head.strip(), tail.strip()
    return name or seg, author


@router.get("")
async def list_references():
    """心理学电子书书目（来自 Wiki.js 004-心理学 分类，按书聚合）"""
    try:
        conn = psycopg2.connect(**WIKI_DB, connect_timeout=3)
    except Exception as e:
        return {"code": 1, "message": f"知识库暂不可用: {e}", "data": {"books": [], "total": 0}}

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT split_part(path, '/', 2) AS seg,
                   COUNT(*) AS chapters,
                   MIN(path) AS first_path,
                   MIN("localeCode") AS locale
            FROM v_psy_chat_pages
            WHERE path LIKE '004-%/%'
              AND title IS NOT NULL AND title != ''
            GROUP BY seg
            HAVING split_part(MIN(path), '/', 2) != ''
            ORDER BY seg
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    books = []
    for row in rows:
        seg = (row["seg"] or "").strip()
        if not seg:
            continue
        m = _SERIAL_RE.match(seg)
        serial = m.group(1) if m else ""
        name, author = _parse_book(seg)
        books.append({
            "serial": serial,
            "name": name,
            "author": author,
            "chapters": int(row["chapters"]),
        })

    # 按 Wiki 编号排序（编号即用户报号学习时使用的号码）
    books.sort(key=lambda b: b["serial"] or "999")
    return {"code": 0, "data": {"books": books, "total": len(books)}}
