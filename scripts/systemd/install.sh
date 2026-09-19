#!/bin/bash
# 一键部署 systemd unit（deepbreath 后端）
# 用法：bash scripts/systemd/install.sh
set -e

UNIT_SRC="$(dirname "$0")/deepbreath-backend.service"
UNIT_DST="/etc/systemd/system/deepbreath-backend.service"

if [ ! -f "$UNIT_SRC" ]; then
    echo "ERROR: $UNIT_SRC not found"
    exit 1
fi

# 杀掉旧的 nohup 进程
echo "→ 杀掉旧的 nohup/手动启动的 uvicorn..."
pkill -9 -f "deep-breath.*uvicorn" 2>/dev/null || true
sleep 2

# 复制 unit 文件
echo "→ 复制 unit 文件到 $UNIT_DST ..."
cp "$UNIT_SRC" "$UNIT_DST"

# 重载 + enable + start
echo "→ systemctl daemon-reload && enable && start..."
systemctl daemon-reload
systemctl enable deepbreath-backend
systemctl restart deepbreath-backend

# 验证
sleep 3
echo ""
echo "=== status ==="
systemctl status deepbreath-backend --no-pager | head -10
echo ""
echo "=== health ==="
curl -sS http://127.0.0.1:8003/api/v1/health
echo ""
echo "=== RSS + Memory limit ==="
PID=$(pgrep -f "uvicorn app.main:app" | head -1)
if [ -n "$PID" ]; then
    ps -o pid,rss,vsz -p "$PID"
fi
