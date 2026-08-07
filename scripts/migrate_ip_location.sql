-- Migration: add IP geolocation columns to login_logs
-- 给 login_logs 表添加地理位置字段
-- 执行方式: psql -h <host> -U <user> -d <db> -f migrate_ip_location.sql

-- 添加字段（使用 IF NOT EXISTS 安全添加）
ALTER TABLE login_logs
    ADD COLUMN IF NOT EXISTS country  VARCHAR(50) DEFAULT '',
    ADD COLUMN IF NOT EXISTS province VARCHAR(50) DEFAULT '',
    ADD COLUMN IF NOT EXISTS city     VARCHAR(50) DEFAULT '';

-- 为地理位置字段添加索引（加速按区域统计查询）
CREATE INDEX IF NOT EXISTS idx_login_logs_province ON login_logs (province) WHERE province != '';
CREATE INDEX IF NOT EXISTS idx_login_logs_city ON login_logs (city) WHERE city != '';
CREATE INDEX IF NOT EXISTS idx_login_logs_country ON login_logs (country) WHERE country != '';

-- 刷新统计（为已有数据补充地理位置 —— 在 Python 服务启动后执行，非 SQL 完成）
-- 执行 SQL 后，请重启后端服务，已有日志将在后续查询中逐步显示地理位置
-- 如需批量补充历史数据的地理位置，请运行 scripts/backfill_ip_location.py

-- 验证
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'login_logs'
  AND column_name IN ('country', 'province', 'city');
