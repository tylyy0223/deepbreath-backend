"""认证 API — 注册 / 登录 / Token 刷新 / 个人信息 + 登录日志"""
import hashlib
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.core.database import get_db, async_session
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, get_optional_user, security_scheme, Roles,
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
from app.services.sms_service import (
    valid_phone, mask_phone, send_code, verify_code,
)

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


def _user_info(user: User, profile: UserProfile | None = None) -> UserInfo:
    """统一构造 UserInfo（手机号脱敏 + 个人资料）"""
    return UserInfo(
        id=user.id, email=user.email, nickname=user.nickname,
        avatar_url=user.avatar_url, role=user.role,
        phone=mask_phone(user.phone),
        phone_bound=bool(user.phone),
        bio=profile.bio if profile else "",
        gender=profile.gender if profile else "",
        birth_year=profile.birth_year if profile else None,
        province=profile.province if profile else "",
    )


async def _check_phone_available(phone: str, db: AsyncSession):
    """手机号可用性：被封禁用户持有 → 403；任何用户持有 → 400（注销不释放，防重复薅赠送）"""
    r = await db.execute(select(User).where(User.phone == phone))
    holder = r.scalar_one_or_none()
    if holder:
        if holder.status == "banned":
            raise HTTPException(status_code=403, detail="该手机号已被系统禁用，无法注册或绑定")
        raise HTTPException(status_code=400, detail="该手机号已被注册")


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
    """用户注册（手机号暂为可选，短信服务待企业资质开通后恢复）"""
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        await _log_login(None, req.email, "register", False, request, "邮箱已注册")
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    # 手机号：当前可选。如填写则校验唯一性 + 验证码
    if req.phone:
        await _check_phone_available(req.phone, db)
        if not await verify_code(req.phone, req.sms_code):
            await _log_login(None, req.email, "register", False, request, "验证码错误")
            raise HTTPException(status_code=400, detail="验证码错误或已过期")

    # 创建用户
    user = User(
        email=req.email,
        phone=req.phone or None,
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

    # 注册赠送 Credits
    from app.services.credits_service import REGISTER_GIFT, add_transaction
    await add_transaction(db, user.id, REGISTER_GIFT, "gift", ref="register", note="新用户注册赠送")

    # 生成 Token
    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id)
    await store_refresh_token(user.id, refresh_token)
    await _log_login(user.id, req.email, "register", True, request)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_user_info(user, profile),
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

    prof_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = prof_result.scalar_one_or_none()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_user_info(user, profile),
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

    prof_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = prof_result.scalar_one_or_none()

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user=_user_info(user, profile),
    )


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """获取当前登录用户信息"""
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    prof_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = prof_result.scalar_one_or_none()
    return _user_info(user, profile)


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


from pydantic import BaseModel, Field


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


@router.put("/password")
async def change_password(
    req: PasswordChangeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改登录密码（验证旧密码；成功后撤销所有 refresh token，其他设备需重新登录）"""
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    password_ok = False
    try:
        if verify_password(req.old_password, user.password_hash):
            password_ok = True
    except Exception:
        pass
    if not password_ok and _verify_legacy_sha256(req.old_password, user.password_hash):
        password_ok = True

    if not password_ok:
        await _log_login(user.id, user.email, "change_password", False, request, "旧密码错误")
        raise HTTPException(status_code=400, detail="当前密码不正确")

    if req.old_password == req.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    user.password_hash = hash_password(req.new_password)
    await db.flush()

    # 撤销所有 refresh token：其他已登录设备失效
    from app.core.redis import revoke_all_refresh_tokens
    await revoke_all_refresh_tokens(user.id)

    await _log_login(user.id, user.email, "change_password", True, request)
    return ApiResponse(message="密码已修改")


class SmsSendRequest(BaseModel):
    phone: str
    scene: str = "register"  # register | bind


@router.post("/sms/send")
async def sms_send(
    req: SmsSendRequest,
    request: Request,
    current_user: dict | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """发送短信验证码（register 免登录，bind 需登录）"""
    phone = (req.phone or "").strip()
    if not valid_phone(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    if req.scene == "bind" and not current_user:
        raise HTTPException(status_code=401, detail="请先登录")

    # 发码前先做占用/封禁校验，避免浪费短信费
    await _check_phone_available(phone, db)

    try:
        await send_code(phone, ip=_get_ip(request))
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))
    return ApiResponse(message="验证码已发送")


class BindPhoneRequest(BaseModel):
    phone: str
    sms_code: str = ""


@router.post("/bind-phone")
async def bind_phone(
    req: BindPhoneRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """存量用户补绑手机号（唯一性/封禁/验证码校验同注册）"""
    phone = (req.phone or "").strip()
    if not valid_phone(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")

    r = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.phone:
        raise HTTPException(status_code=400, detail="已绑定手机号，如需更换请联系管理员")

    await _check_phone_available(phone, db)
    if not await verify_code(phone, req.sms_code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    user.phone = phone
    await db.flush()
    await _log_login(user.id, user.email, "bind_phone", True, request, mask_phone(phone) or "")
    return {"code": 0, "message": "绑定成功", "data": {"phone": mask_phone(phone), "phone_bound": True}}


@router.post("/logout")
async def logout(
    current_user: dict = Depends(get_current_user),
    request: Request = None,
    token: str = Depends(security_scheme),
):
    """登出：撤销 refresh token + 加入 access token 黑名单"""
    from app.core.redis import revoke_all_refresh_tokens, redis_client
    await revoke_all_refresh_tokens(current_user["user_id"])
    # Access Token 黑名单：存到 Redis，TTL 设为剩余有效期
    payload = decode_token(token.credentials)
    if payload and payload.get("exp"):
        import time
        ttl = max(1, int(payload["exp"] - time.time()))
        await redis_client.setex(f"blacklist:access:{token.credentials}", ttl, "1")
    if request:
        await _log_login(current_user["user_id"], str(current_user["user_id"]), "logout", True, request)
    return ApiResponse(message="已登出")
