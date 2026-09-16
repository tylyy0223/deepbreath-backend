-- ============================================================
-- sync_counters.sql — 校正 community_posts 反规范化计数器
--
-- 背景:
--   like_count / reply_count 是 CommunityPost 表的反规范化字段,
--   应用层用 +/- 1 维护. 并发或历史数据可能漂移.
--
-- 用法 (dev 或 prod 上跑一次, 必须 dry-run 先看差异再正式):
--   PGPASSWORD=... psql -h ... -U deepbreath -d deepbreath -f sync_counters.sql
-- ============================================================

BEGIN;

-- 1. 校正 like_count (从 community_likes 实际计数)
WITH actual_likes AS (
    SELECT post_id, COUNT(*) AS cnt
    FROM community_likes
    GROUP BY post_id
)
UPDATE community_posts p
SET like_count = COALESCE(l.cnt, 0)
FROM (
    SELECT post_id, cnt FROM actual_likes
    UNION ALL
    SELECT id, 0 FROM community_posts WHERE id NOT IN (SELECT post_id FROM actual_likes)
) l
WHERE p.id = l.post_id;

-- 2. 校正 reply_count (从 community_replies 实际计数, status='active')
WITH actual_replies AS (
    SELECT post_id, COUNT(*) AS cnt
    FROM community_replies
    WHERE status = 'active'
    GROUP BY post_id
)
UPDATE community_posts p
SET reply_count = COALESCE(r.cnt, 0)
FROM (
    SELECT post_id, cnt FROM actual_replies
    UNION ALL
    SELECT id, 0 FROM community_posts WHERE id NOT IN (SELECT post_id FROM actual_replies)
) r
WHERE p.id = r.post_id;

-- 3. 显示差异最大的前 10 条 (供人工 review)
SELECT
    p.id,
    LEFT(p.title, 30) AS title,
    p.like_count AS cur_likes,
    (SELECT COUNT(*) FROM community_likes WHERE post_id = p.id) AS actual_likes,
    p.reply_count AS cur_replies,
    (SELECT COUNT(*) FROM community_replies WHERE post_id = p.id AND status = 'active') AS actual_replies
FROM community_posts p
WHERE p.like_count != (SELECT COUNT(*) FROM community_likes WHERE post_id = p.id)
   OR p.reply_count != (SELECT COUNT(*) FROM community_replies WHERE post_id = p.id AND status = 'active')
ORDER BY ABS(p.like_count - (SELECT COUNT(*) FROM community_likes WHERE post_id = p.id)) DESC
LIMIT 10;

COMMIT;