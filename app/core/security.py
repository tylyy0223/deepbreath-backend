"""JWT 认证 + 密码哈希 + RBAC 权限"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)


# ============================================================
# 密码工具
# ============================================================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ============================================================
# JWT Token 工具
# ============================================================

def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": expire,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": expire,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


# ============================================================
# 角色定义
# ============================================================

class Roles:
    USER = "user"
    EDITOR = "editor"
    MODERATOR = "moderator"
    ADMIN = "admin"

    # 角色层级：数字越大权限越高
    HIERARCHY = {USER: 0, EDITOR: 1, MODERATOR: 2, ADMIN: 3}

    @classmethod
    def has_role(cls, user_role: str, required_role: str) -> bool:
        return cls.HIERARCHY.get(user_role, -1) >= cls.HIERARCHY.get(required_role, 999)


# ============================================================
# 认证依赖
# ============================================================

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> dict:
    """解析 JWT 返回用户信息，未登录抛出 401；检查黑名单"""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    # 检查 Access Token 是否已被注销（黑名单）
    from app.core.redis import redis_client
    if await redis_client.exists(f"blacklist:access:{credentials.credentials}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 已注销，请重新登录")
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效或已过期")
    return {"user_id": int(payload["sub"]), "role": payload.get("role", Roles.USER)}


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Optional[dict]:
    """可选认证：登录了返回用户信息，没登录返回 None"""
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        return None
    return {"user_id": int(payload["sub"]), "role": payload.get("role", Roles.USER)}


def require_role(role: str):
    """权限装饰器工厂：要求最低角色"""
    async def checker(current_user: dict = Depends(get_current_user)):
        if not Roles.has_role(current_user["role"], role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"需要 {role} 及以上权限")
        return current_user
    return checker
