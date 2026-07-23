"""API 响应格式统一中间件

所有非异常的 JSON 响应统一包装为:
  {"code": 0, "message": "ok", "data": <原始响应>}

如果原始响应已包含 "code" 字段 → 视为已包装，跳过。
"""
import json
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware


# 不想被包装的路由前缀（如 /docs, /openapi.json 等）
_SKIP_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/api/v1/health")


def _should_skip(path: str) -> bool:
    return any(path.startswith(p) for p in _SKIP_PREFIXES)


def _is_streaming(content_type: str | None) -> bool:
    if not content_type:
        return False
    return "text/event-stream" in content_type or "application/octet-stream" in content_type


class ApiResponseMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 非 200 状态码（如 401/402/404 等）不包装，让异常处理器负责
        if response.status_code != 200:
            return response

        # 跳过文档、健康检查、流式响应
        if _should_skip(request.url.path):
            return response

        content_type = response.headers.get("content-type", "")
        if _is_streaming(content_type):
            return response

        # 读取响应体
        body = b""
        # 直接迭代 response.body_iterator（标准 Starlette 属性），不用 __dict__
        try:
            async for chunk in response.body_iterator:
                body += chunk
        except Exception:
            return response
        if not body:
            return response

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(content=body, status_code=response.status_code,
                            headers=dict(response.headers), media_type=content_type)

        # 已有标准格式 → 跳过
        if isinstance(data, dict) and "code" in data:
            return Response(content=body, status_code=response.status_code,
                            headers=dict(response.headers), media_type=content_type)

        # 包装
        wrapped = {"code": 0, "message": "ok", "data": data}
        return JSONResponse(content=wrapped, status_code=response.status_code,
                            headers=dict(response.headers))
