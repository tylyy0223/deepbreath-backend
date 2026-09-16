"""深呼吸 DeepBreath — FastAPI 应用入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 DB，关闭时清理连接"""
    if settings.DEBUG:
        await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# === CORS 白名单 ===
# settings.CORS_ORIGINS 默认只有 dev 本地; 生产环境必须在 .env 显式设置:
#   CORS_ORIGINS=https://luoyuyu.cn,https://www.luoyuyu.cn
# 安全: 不允许 allow_origins=[*] + allow_credentials=True 组合 (CSRF 公开风险)
import os as _os
_cors_origins = settings.CORS_ORIGINS
if isinstance(_cors_origins, str):
    _cors_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
if "*" in _cors_origins:
    raise RuntimeError(
        "CORS 拒绝 allow_origins=[*] + allow_credentials=True 组合 (CSRF 公开风险). "
        "请在 .env 显式设置白名单, 例: CORS_ORIGINS=https://luoyuyu.cn"
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    max_age=86400,
)


@app.middleware("http")
async def track_online_users(request: Request, call_next):
    """在线用户追踪：带有效 access token 的 /api/v1 请求刷新 online:{user_id}（5 分钟窗口）

    供管理后台「并发用户监控」使用；JWT 本地解码，无 DB 查询，开销 <1ms。
    """
    try:
        if request.url.path.startswith("/api/v1"):
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                from app.core.security import decode_token
                from app.core.redis import redis_client
                payload = decode_token(auth[7:].strip())
                if payload and payload.get("type") == "access":
                    uid = int(payload["sub"])
                    await redis_client.set(
                        f"online:{uid}",
                        int(__import__("time").time()),
                        ex=300,
                    )
    except Exception:
        pass
    return await call_next(request)

# API 响应格式统一（P1-#7：非 stream 的 200 响应自动包装 {code,message,data}）
# P1-#7 API 中间件暂禁用排查登录问题
# from app.core.response_middleware import ApiResponseMiddleware
# app.add_middleware(ApiResponseMiddleware)

# 健康检查
@app.get("/api/v1/health")
async def health_check():
    from sqlalchemy import text
    from app.core.database import async_session
    from app.core.redis import redis_client

    db_ok = False
    try:
        async with async_session() as session:
            await session.execute(text("select 1"))
        db_ok = True
    except Exception:
        pass

    redis_ok = False
    try:
        redis_ok = await redis_client.ping()
    except Exception:
        pass

    return {
        "status": "ok",
        "db": "connected" if db_ok else "disconnected",
        "redis": "connected" if redis_ok else "disconnected",
    }


# 注册路由
from app.api.v1 import auth as auth_router
from app.api.v1 import chat as chat_router
from app.api.v1 import admin as admin_router
from app.api.v1 import content as content_router
from app.api.v1 import breath as breath_router
from app.api.v1 import diary as diary_router
from app.api.v1 import checkin as checkin_router
from app.api.v1 import community as community_router
from app.api.v1 import tts as tts_router
from app.api.v1 import email_api as email_router
from app.api.v1 import credits as credits_router
from app.api.v1 import scales as scales_router
from app.api.v1 import references as references_router
from app.api.v1 import upload as upload_router
from app.api.v1 import audio as audio_router
from app.api.v1 import assessment as assessment_router

app.include_router(auth_router.router, tags=["认证"])
app.include_router(chat_router.router, tags=["AI对话"])
app.include_router(admin_router.router, tags=["管理后台"])
app.include_router(content_router.router, tags=["科普内容"])
app.include_router(breath_router.router, tags=["呼吸练习"])
app.include_router(diary_router.router, tags=["情绪日记"])
app.include_router(checkin_router.router, tags=["签到"])
app.include_router(community_router.router, tags=["社区"])
app.include_router(tts_router.router, tags=["TTS"])
app.include_router(email_router.router, tags=["邮件"])
app.include_router(credits_router.router, tags=["Credits"])
app.include_router(scales_router.router, tags=["心理量表"])
app.include_router(references_router.router, tags=["参考文献"])
from app.api.v1 import book_listen as book_listen_router
from app.api.v1 import reading_progress as reading_router
app.include_router(book_listen_router.router, tags=["AI听书"])
app.include_router(reading_router.router, tags=["读书进度"])
app.include_router(upload_router.router, tags=["文件上传"])
app.include_router(audio_router.router, tags=["语音识别"])
app.include_router(assessment_router.router, tags=["心理评估"])


@app.get("/")
async def root():
    """API 首页"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>深呼吸 DeepBreath API</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#f8f6f3;color:#3d3d3d;display:flex;justify-content:center;padding:40px 20px}}
.card{{background:#fff;border-radius:16px;padding:32px;max-width:600px;width:100%;box-shadow:0 2px 16px rgba(0,0,0,.06)}}
h1{{font-size:24px;color:#7c8a7a;margin-bottom:4px}}h2{{font-size:14px;color:#999;font-weight:400;margin-bottom:24px}}
.status{{display:flex;align-items:center;gap:8px;margin-bottom:24px;padding:12px;background:#f0f7f0;border-radius:8px}}
.dot{{width:10px;height:10px;border-radius:50%;background:#4caf50;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
h3{{font-size:14px;margin-bottom:12px;color:#666}}
ul{{list-style:none}}li{{padding:6px 0;font-size:13px}}a{{color:#7c8a7a;text-decoration:none}}a:hover{{text-decoration:underline}}
.method{{display:inline-block;width:42px;font-size:11px;font-weight:bold;color:#999}}
</style></head>
<body>
<div class="card">
<h1>🍃 深呼吸 DeepBreath</h1>
<h2>Psychology Platform API v{settings.APP_VERSION}</h2>
<div class="status"><div class="dot"></div> 服务运行中</div>
<h3>📡 公开接口</h3>
<ul>
<li><span class="method">GET</span> <a href="/api/health">/api/health</a> 健康检查</li>
<li><span class="method">POST</span> /api/v1/auth/register 注册</li>
<li><span class="method">POST</span> /api/v1/auth/login 登录</li>
<li><span class="method">GET</span> <a href="/api/v1/chat/modes">/api/v1/chat/modes</a> 对话模式</li>
<li><span class="method">GET</span> <a href="/api/v1/content/categories">/api/v1/content/categories</a> 内容分类</li>
<li><span class="method">GET</span> <a href="/api/v1/breath/exercises">/api/v1/breath/exercises</a> 呼吸练习</li>
</ul>
<h3 style="margin-top:16px">📖 文档</h3>
<ul>
<li><a href="/docs">/docs</a> Swagger API 文档</li>
<li><a href="/redoc">/redoc</a> ReDoc API 文档</li>
</ul>
<p style="margin-top:20px;font-size:12px;color:#aaa">端口 8001 · 后端 API 服务 · 用户端和管理后台前端即将上线</p>
</div>
</body></html>""")


@app.get("/api/health")
async def health_check_simple():
    """健康检查端点（轻量）"""
    return {"status": "ok", "version": settings.APP_VERSION, "name": settings.APP_NAME}
