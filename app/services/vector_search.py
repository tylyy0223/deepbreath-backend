"""DeepBreath 向量 RAG 检索（47.103.62.70）

使用 SQLite 向量库（build_vector_rag.py 构建）+ SiliconFlow bge-large-zh-v1.5 嵌入。
返回格式与 rag_search.search_wiki 兼容：{"results": [{title, path, page_url, content, _similarity}], "total": N}

双通道集成：chat.py 中先调 vector_search 再调 search_wiki，按 title 去重合并。
"""
import json, logging, math, os, re, sqlite3, struct, time
import httpx

from app.services.env import ensure_env  # 统一 env 加载

ensure_env()

# === 应急禁用（2026-09-19 OOM fix）===
# 向量数据库 800MB，加载到 Python 内存导致 worker 涨到 2.6GB → OOM Killed
# 临时禁用 vector_search（依赖 ILIKE 关键词检索代替），
# 恢复需要换 Qdrant/Milvus 等专用向量库。
_VECTOR_SEARCH_DISABLED = os.environ.get("DISABLE_VECTOR_SEARCH", "1") == "1"

# 独立脚本/测试路径兜底：ensure_env 可能因 pydantic-settings 已加载而跳过 os.environ 注入，
# 此时手动从 .env 文件补读（幂等，仅在 os.environ 缺失时注入）
def _env_fallback():
    if os.environ.get("SILICONFLOW_API_KEY"):
        return
    env_file = "/root/deep-breath/backend/.env"
    try:
        if os.path.isfile(env_file):
            for line in open(env_file, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip()
                    if k and k not in os.environ:
                        os.environ[k] = v.strip()
    except Exception:
        pass

_env_fallback()

logger = logging.getLogger("deepbreath.vector_search")

VDB_PATH = "/root/deep-breath/backend/app/data/vector_rag.sqlite"
EMBED_API = "https://api.siliconflow.cn/v1/embeddings"
EMBED_MODEL = "BAAI/bge-large-zh-v1.5"
WIKI_BASE_URL = "https://luoyuyu.cn"

_EMBED_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
_db = None            # 延迟加载的向量库
_db_rows = None       # [(id, title, path, locale, section, text, vector)]
_loaded_at = 0.0
_REFRESH_TTL = 3600   # 1 小时重载（支持重建后热更新）


def _get_key():
    global _EMBED_KEY
    if not _EMBED_KEY:
        _EMBED_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
    return _EMBED_KEY


def _load_db(force=False):
    """延迟加载向量库（进程内缓存，支持 TTL 刷新）"""
    if _VECTOR_SEARCH_DISABLED:
        # 应急：禁用向量加载，避免 800MB SQLite + 向量驻留内存导致 OOM
        return []
    global _db, _db_rows, _loaded_at
    if _db is None:
        if not os.path.isfile(VDB_PATH):
            logger.warning("向量库文件不存在: %s", VDB_PATH)
            _db_rows = []
            return _db_rows
        try:
            os.makedirs(os.path.dirname(VDB_PATH), exist_ok=True)
            _db = sqlite3.connect(VDB_PATH)
        except Exception as e:
            logger.error("向量库打开失败: %s", e)
            _db_rows = []
            return _db_rows
    if _db_rows is None or force or (time.time() - _loaded_at > _REFRESH_TTL):
        try:
            cur = _db.execute("SELECT id, title, path, locale, section, text, vector FROM chunks")
            rows = cur.fetchall()
            _db_rows = []
            for rid, title, path, locale, section, text, vblob in rows:
                try:
                    if isinstance(vblob, bytes):
                        # 二进制 float32 格式
                        n = len(vblob) // 4
                        vec = list(struct.unpack(f"{n}f", vblob))
                    else:
                        vec = json.loads(vblob)
                except Exception:
                    continue
                _db_rows.append((rid, title, path, locale, section, text, vec))
            _loaded_at = time.time()
            logger.info("向量库加载: %d chunks (%s)", len(_db_rows), VDB_PATH)
        except Exception as e:
            logger.error("向量库加载失败: %s", e)
            _db_rows = []
    return _db_rows


def _cosine(a, b):
    dot = 0.0
    for x, y in zip(a, b):
        dot += x * y
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def _embed(text):
    """单条文本嵌入（带重试）"""
    key = _get_key()
    for attempt in range(3):
        try:
            r = httpx.post(EMBED_API,
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": EMBED_MODEL, "input": [text[:500]]},
                           timeout=30)
            if r.status_code == 200:
                return r.json()["data"][0]["embedding"]
            logger.warning("embed HTTP %s: %s", r.status_code, r.text[:120])
        except Exception as e:
            logger.warning("embed err: %s", e)
        time.sleep(2)
    return None


def search(query, limit=5, threshold=0.30):
    """向量语义检索。返回与 search_wiki 兼容的 dict。"""
    t0 = time.time()
    if _VECTOR_SEARCH_DISABLED:
        return {"results": [], "total": 0, "query": query, "engine": "vector-disabled"}
    rows = _load_db()
    if not rows:
        logger.warning("向量库为空，跳过向量检索")
        return {"results": [], "total": 0, "query": query, "engine": "vector"}

    qvec = _embed(query)
    if qvec is None:
        return {"results": [], "total": 0, "query": query, "engine": "vector"}

    scored = []
    for rid, title, path, locale, section, text, vec in rows:
        s = _cosine(qvec, vec)
        if s >= threshold:
            scored.append((s, rid, title, path, locale, section, text))
    scored.sort(key=lambda x: -x[0])

    # 按 title 去重（保留每本书得分最高的片段）
    seen = set()
    results = []
    for s, rid, title, path, locale, section, text in scored[:limit * 3]:
        if title in seen:
            continue
        seen.add(title)
        clean = re.sub(r"<[^>]+>", "", text)[:600]
        page_url = f"{WIKI_BASE_URL}/{locale}/{path}" if path else ""
        results.append({
            "title": title, "path": path, "page_url": page_url,
            "description": "", "content": clean,
            "snippet": clean, "_similarity": round(s, 4),
            "section": (section or "")[:60],
        })
        if len(results) >= limit:
            break

    logger.info("向量检索 '%s': %d 结果 (%.0fms)", query, len(results), (time.time() - t0) * 1000)
    return {"results": results, "total": len(results), "query": query, "engine": "vector"}


# 兼容别名（供 chat.py 以 vector_search(query, limit=N) 调用）
def search_wiki(query, limit=5):
    return search(query, limit=limit)


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "如何克服演讲焦虑"
    r = search(q, limit=5)
    print(f"查询: {q}")
    for x in r["results"]:
        print(f"  [{x['_similarity']:.3f}] {x['title']} :: {x['section']}")
        print(f"      {x['content'][:80]}")
