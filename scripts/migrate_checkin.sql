-- Migration: create standalone checkins table
-- 创建独立签到表，与日记模块分离
-- 执行方式: psql -h <host> -U <user> -d <db> -f migrate_checkin.sql

-- 创建签到表
CREATE TABLE IF NOT EXISTS checkins (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    check_date      DATE NOT NULL,
    streak_count    INTEGER DEFAULT 1,
    credits_earned  INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now(),

    -- 每个用户每天只能签到一次
    CONSTRAINT uq_checkins_user_date UNIQUE (user_id, check_date)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_checkins_user_id ON checkins (user_id);
CREATE INDEX IF NOT EXISTS idx_checkins_date ON checkins (check_date);
CREATE INDEX IF NOT EXISTS idx_checkins_user_date ON checkins (user_id, check_date);

-- 从旧 diary 模块迁移历史签到数据（如果 login_logs 或旧 check_in 表有数据）
-- 注：旧签到数据在 app/models/diary.py 的 CheckIn 模型中，如果存在旧表请手动迁移：
--
-- INSERT INTO checkins (user_id, check_date, streak_count, credits_earned, created_at)
-- SELECT user_id, check_date, streak_count, 2, created_at
-- FROM old_checkins_table
-- ON CONFLICT (user_id, check_date) DO NOTHING;

-- 外键约束（可选，保留数据完整性）
-- ALTER TABLE checkins ADD CONSTRAINT fk_checkins_user
--     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- 验证
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'checkins'
ORDER BY ordinal_position;
