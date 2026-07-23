"""认证相关 Pydantic Schemas"""
from pydantic import BaseModel, EmailStr, field_validator
import re


class RegisterRequest(BaseModel):
    email: str
    password: str
    nickname: str = ""
    phone: str = ""            # 暂时可选（短信服务待企业资质开通）
    sms_code: str = ""

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if "@" not in v or len(v) > 255:
            raise ValueError("邮箱格式不正确")
        return v.lower().strip()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError("密码至少 6 位")
        return v

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v):
        return v.strip()[:50]

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        v = (v or "").strip()
        if v == "":
            return v       # 手机号暂时可选
        if not re.match(r"^1[3-9]\d{9}$", v):
            raise ValueError("手机号格式不正确")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    id: int
    email: str
    nickname: str
    avatar_url: str
    role: str
    phone: str | None = None       # 脱敏后的手机号（138****1234）
    phone_bound: bool = False      # 前端据此触发强制补绑
    # 个人资料（来自 user_profiles 表）
    bio: str = ""
    gender: str = ""
    birth_year: int | None = None
    province: str = ""

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    nickname: str | None = None
    bio: str | None = None
    gender: str | None = None
    birth_year: int | None = None
    province: str | None = None


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict | list | None = None
