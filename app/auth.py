"""认证 API — 注册 / 登录 / Token 刷新 / 个人信息 + 登录日志"""
import hashlib
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.core.database import get_db, async_session
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, security_scheme, Roles,
)
from app.core.redis import (
    store_refresh_token, validate_refresh_token, revoke_refresh_token,
)
from app.models.user import User, UserProfile
from app.models.cache import LoginLog
from app.schemas.auth import (
    RegisterRequest, LoginRequest, RefreshRequest,
    TokenResponse, UserInfo, UserProfileUpdate, ApiResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else ""


async def _log_login(user_id: int | None, email: str, action: str, success: bool, request: Request, detail: str = ""):
    try:
        db = async_session()
        db.add(LoginLog(
            user_id=user_id, email=email, action=action, success=success,
            ip_address=_get_ip(request),
            user_agent=(request.headers.get("User-Agent", "") or "")[:500],
            detail=detail,
        ))
        await db.commit()
    except Exception:
        pass
    finally:
        await db.close()


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        await _log_login(None, req.email, "register", False, request, "邮箱已注册")
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    # 创建用户
    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        nickname=req.nickname or req.email.split("@")[0],
        role=Roles.USER,
        status="active",
    )
    db.add(user)
    await db.flush()

    # 创建用户档案
    profile = UserProfile(user_id=user.id)
    db.add(profile)
    await db.flush()

    # 生成 Token
    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id)
    await store_refresh_token(user.id, refresh_token)
    await _log_login(user.id, req.email, "register", True, request)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserInfo(
            id=user.id, email=user.email, nickname=user.nickname,
            avatar_url=user.avatar_url, role=user.role,
        ),
    )


import hashlib

def _verify_legacy_sha256(password: str, stored_hash: str) -> bool:
    """兼容旧 psy-chat 的 SHA-256 + salt 密码"""
    legacy = hashlib.sha256((password + "psy2024salt").encode()).hexdigest()
    return legacy == stored_hash


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user:
        await _log_login(None, req.email, "login", False, request, "用户不存在")
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    password_ok = False
    try:
        if verify_password(req.password, user.password_hash):
            password_ok = True
    except Exception:
        pass

    if not password_ok and _verify_legacy_sha256(req.password, user.password_hash):
        user.password_hash = hash_password(req.password)
        await db.flush()
        password_ok = True

    if not password_ok:
        await _log_login(user.id, req.email, "login", False, request, "密码错误")
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if user.status == "banned":
        await _log_login(user.id, req.email, "login", False, request, "账号已封禁")
        raise HTTPException(status_code=403, detail="账号已被封禁")

    if user.status == "deleted":
        await _log_login(user.id, req.email, "login", False, request, "账号已注销")
        raise HTTPException(status_code=403, detail="账号已注销")

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id)
    await store_refresh_token(user.id, refresh_token)
    await _log_login(user.id, req.email, "login", True, request)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserInfo(
            id=user.id, email=user.email, nickname=user.nickname,
            avatar_url=user.avatar_url, role=user.role,
        ),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """刷新 Access Token"""
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Refresh Token 无效或已过期")

    user_id = int(payload["sub"])

    # 验证 refresh token 是否还存在于 Redis
    if not await validate_refresh_token(user_id, req.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh Token 已被撤销")

    # 查询用户
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    # 轮换 refresh token
    await revoke_refresh_token(user_id, req.refresh_token)
    new_access = create_access_token(user.id, user.role)
    new_refresh = create_refresh_token(user.id)
    await store_refresh_token(user.id, new_refresh)

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user=UserInfo(
            id=user.id, email=user.email, nickname=user.nickname,
            avatar_url=user.avatar_url, role=user.role,
        ),
    )


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """获取当前登录用户信息"""
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserInfo(
        id=user.id, email=user.email, nickname=user.nickname,
        avatar_url=user.avatar_url, role=user.role,
    )


@router.put("/profile")
async def update_profile(
    req: UserProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新个人资料"""
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.nickname is not None:
        user.nickname = req.nickname[:50]

    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if profile:
        for field in ["bio", "gender", "birth_year", "province"]:
            val = getattr(req, field, None)
            if val is not None:
                setattr(profile, field, val)

    await db.flush()
    return ApiResponse(message="资料已更新")


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user), request: Request = None):
    """登出（撤销所有 refresh token）"""
    from app.core.redis import revoke_all_refresh_tokens
    await revoke_all_refresh_tokens(current_user["user_id"])
    if request:
        await _log_login(current_user["user_id"], str(current_user["user_id"]), "logout", True, request)
    return ApiResponse(message="已登出")
