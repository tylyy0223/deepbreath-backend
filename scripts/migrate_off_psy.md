# DeepBreath 脱离 psy-chat 依赖 — 正确操作步骤

## 现状（已做）
- psychat.service 已 stop+disable+mask ✅
- DeepBreath services/ 下已有 `deepbreath_chatbot.py` / `deepbreath_rag.py`（内迁版，不依赖 psy-chat）✅
- `app/api/v1/chat.py` 的 import 已指向 app.services 下的文件 ✅
- `app/services/config.py` 已创建（最小化替代 psy-chat 的 config.py）✅
- `app/services/chatbot.py` + `rag_search.py` 从 psy-chat 复制（保底可用）✅

## 待执行（服务器连接恢复后一次性完成）

```bash
ssh root@100.119.151.62
cd /root/deep-breath/backend

# 1. 确认 config.py 存在
cat app/services/config.py | head -5

# 2. 语法检查
venv/bin/python -m py_compile app/services/config.py app/services/chatbot.py app/services/rag_search.py app/services/chat_service.py

# 3. 清理残留的 psy-chat 引用
sed -i '/sys.path.insert.*psy-chat/d' app/services/email_sender.py

# 4. 重启
systemctl restart deepbreath && sleep 8 && systemctl is-active deepbreath

# 5. 验证
curl -s http://127.0.0.1:8003/api/v1/health
TA=... # login
curl -s http://127.0.0.1:8003/api/v1/chat/sessions -H "Authorization: Bearer $TA" # 检查会话
```

## 验证通过后（清理 V1）
```bash
# 移除 nginx 的 /api/ → 5002 路由
vim /etc/nginx/conf.d/psychat.conf  # 注释 proxy_pass 5002 或删文件
nginx -s reload

# 删除 V1 代码（可回收 ~210MB）
rm -rf /root/psy-chat
```

**注意**：config.py 必须保留在 services/ 下——chatbot.py 和 rag_search.py 需要通过 `from config import ...` 读到 DB 密码和 DeepSeek Key（它们从 os.environ 取值，运行时由 systemd 的 EnvironmentFile 注入）。
