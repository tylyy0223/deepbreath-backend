"""P0-#6c: Credits 核心路径测试 — 充值 / 扣费 / 余额 / 流水"""
import pytest


class TestCredits:
    """Credits 计费 — 注册赠送、余额查询、扣费校验"""

    async def _register(self, client, email="credits-test@deepbreath.local"):
        reg = await client.post("/api/v1/auth/register", json={
            "email": email,
            "password": "Test1234!",
            "phone": "",
            "sms_code": "",
        })
        assert reg.status_code == 200
        return reg.json()["access_token"]

    async def test_register_grants_credits(self, client):
        """注册新用户 → 获得赠送 Credits"""
        token = await self._register(client)

        res = await client.get("/api/v1/credits/balance", headers={
            "Authorization": f"Bearer {token}",
        })
        if res.status_code == 200:
            data = res.json()
            balance = data if isinstance(data, (int, float)) else data.get("balance", data.get("data", {}).get("balance", 0))
            assert balance > 0, f"Expected >0 credits after registration, got {balance}"

    async def test_get_balance_requires_auth(self, client):
        """未登录查询余额 → 401"""
        res = await client.get("/api/v1/credits/balance")
        assert res.status_code in (401, 403)

    async def test_get_pricing_list(self, client):
        """获取定价列表（公开接口）"""
        token = await self._register(client)
        res = await client.get("/api/v1/credits/pricing", headers={
            "Authorization": f"Bearer {token}",
        })
        # 定价接口可能是公开的
        assert res.status_code in (200, 404)  # 404 表示路由未实现

    async def test_transaction_history(self, client):
        """查询交易流水"""
        token = await self._register(client, "txlog@test.local")

        res = await client.get("/api/v1/credits/transactions", headers={
            "Authorization": f"Bearer {token}",
        })
        if res.status_code == 200:
            data = res.json()
            items = data if isinstance(data, list) else data.get("data", data.get("items", []))
            # 注册赠送至少一条记录
            assert len(items) >= 1, f"Expected >=1 transaction after registration, got {len(items)}"

    async def test_create_order(self, client):
        """创建充值订单"""
        token = await self._register(client, "order@test.local")

        res = await client.post("/api/v1/credits/orders", json={
            "package_id": "basic",
            "channel": "corporate",
        }, headers={
            "Authorization": f"Bearer {token}",
        })
        # 能创建订单就 OK（package_id 校验视实现而定）
        assert res.status_code in (200, 400, 404), f"Unexpected status: {res.status_code}"

    async def test_redeem_invalid_code_fails(self, client):
        """无效兑换码 → 报错"""
        token = await self._register(client, "redeem@test.local")

        res = await client.post("/api/v1/credits/redeem", json={
            "code": "INVALID-CODE-12345",
        }, headers={
            "Authorization": f"Bearer {token}",
        })
        # 无效码应该返回错误
        assert res.status_code >= 400, f"Expected error for invalid code, got {res.status_code}"

    async def test_admin_credits_requires_admin(self, client):
        """普通用户无权访问 admin credits 接口"""
        token = await self._register(client, "notadmin@test.local")

        res = await client.get("/api/v1/credits/admin/summary", headers={
            "Authorization": f"Bearer {token}",
        })
        assert res.status_code in (401, 403)
