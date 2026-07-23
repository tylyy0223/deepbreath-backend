"""P0-#6a: 认证核心路径测试 — 注册 / 登录 / Token 刷新 / 登出"""
import pytest


class TestAuth:
    """认证完整生命周期"""

    async def test_register_success(self, client):
        """注册新用户 → 返回 access_token + refresh_token"""
        res = await client.post("/api/v1/auth/register", json={
            "email": "test@deepbreath.local",
            "password": "Test1234!",
            "nickname": "测试用户",
            "phone": "",
            "sms_code": "",
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "test@deepbreath.local"
        assert data["user"]["nickname"] == "测试用户"

    async def test_register_duplicate_email_blocked(self, client):
        """重复邮箱注册 → 400"""
        # 第一次注册已在上面完成（test_register_success），这里再注册一次
        res = await client.post("/api/v1/auth/register", json={
            "email": "test@deepbreath.local",
            "password": "Test1234!",
            "phone": "",
            "sms_code": "",
        })
        assert res.status_code == 400

    async def test_register_weak_password_blocked(self, client):
        """弱密码 → 422（Pydantic 校验）"""
        res = await client.post("/api/v1/auth/register", json={
            "email": "weak@test.local",
            "password": "123",
            "phone": "",
            "sms_code": "",
        })
        assert res.status_code == 422

    async def test_login_success(self, client):
        """已注册用户登录 → 返回 Token"""
        # 先注册
        await client.post("/api/v1/auth/register", json={
            "email": "login-test@deepbreath.local",
            "password": "Test1234!",
            "phone": "",
            "sms_code": "",
        })
        # 再登录
        res = await client.post("/api/v1/auth/login", json={
            "email": "login-test@deepbreath.local",
            "password": "Test1234!",
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_login_wrong_password(self, client):
        """错误密码 → 401"""
        res = await client.post("/api/v1/auth/login", json={
            "email": "login-test@deepbreath.local",
            "password": "WrongPassword!",
        })
        assert res.status_code == 401

    async def test_refresh_token_works(self, client):
        """用 refresh_token 换取新的 access_token"""
        reg = await client.post("/api/v1/auth/register", json={
            "email": "refresh@test.local",
            "password": "Test1234!",
            "phone": "",
            "sms_code": "",
        })
        refresh_token = reg.json()["refresh_token"]

        res = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        # 新 token 应该不同
        assert data["access_token"] != reg.json()["access_token"]

    async def test_me_requires_auth(self, client):
        """未登录访问 /me → 401"""
        res = await client.get("/api/v1/auth/me")
        assert res.status_code in (401, 403)

    async def test_me_with_valid_token(self, client):
        """登录后 /me 返回用户信息"""
        reg = await client.post("/api/v1/auth/register", json={
            "email": "me-test@deepbreath.local",
            "password": "Test1234!",
            "phone": "",
            "sms_code": "",
        })
        token = reg.json()["access_token"]

        res = await client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert res.status_code == 200
        assert res.json()["email"] == "me-test@deepbreath.local"

    async def test_register_without_phone_ok(self, client):
        """不填手机号也能注册（当前短信未开通）"""
        res = await client.post("/api/v1/auth/register", json={
            "email": "nophone@test.local",
            "password": "Test1234!",
            "phone": "",
            "sms_code": "",
        })
        assert res.status_code == 200
        assert res.json()["user"]["phone_bound"] is False
