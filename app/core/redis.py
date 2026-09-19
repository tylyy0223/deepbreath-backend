"""Redis 连接 & 工具函数"""
import redis.asyncio as aioredis
from app.core.config import settings

redis_client = aioredis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
)


async def get_redis():
    """FastAPI 依赖注入"""
    return redis_client


# ============================================================
# 常用缓存工具
# ============================================================

async def cache_get(key: str) -> str | None:
    return await redis_client.get(key)


async def cache_set(key: str, value: str, expire_seconds: int = 3600):
    await redis_client.set(key, value, ex=expire_seconds)


async def cache_delete(key: str):
    await redis_client.delete(key)


async def cache_exists(key: str) -> bool:
    return await redis_client.exists(key) > 0


# ============================================================
# Refresh Token 存储
# ============================================================

async def store_refresh_token(user_id: int, token: str):
    """Redis 存储 refresh token（7 天过期）"""
    key = f"refresh_token:{user_id}"
    await redis_client.sadd(key, token)
    await redis_client.expire(key, settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)


async def validate_refresh_token(user_id: int, token: str) -> bool:
    """验证 refresh token 是否有效"""
    key = f"refresh_token:{user_id}"
    return await redis_client.sismember(key, token)


async def revoke_refresh_token(user_id: int, token: str):
    """撤销单个 refresh token"""
    key = f"refresh_token:{user_id}"
    await redis_client.srem(key, token)


async def revoke_all_refresh_tokens(user_id: int):
    """撤销该用户所有 refresh token（改密码/登出所有设备时用）"""
    key = f"refresh_token:{user_id}"
    await redis_client.delete(key)


# ============================================================
# 速率限制
# ============================================================

async def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """原子速率限制 (INCR + EXPIRE pipeline)，返回 True 表示允许

    注意：原代码用 expire(..., nx=True)，但 Redis 7.0+ 才支持 NX 参数。
    Redis 6.x 会报 "wrong number of arguments for 'expire' command" → pipeline abort → chat 500。
    这里去掉 nx=True（每次 EXPIRE 重置 TTL，窗口可能略长，但功能正确且兼容 6.x/7.x）。
    """
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds)
    count, _ = await pipe.execute()
    return count <= max_requests
