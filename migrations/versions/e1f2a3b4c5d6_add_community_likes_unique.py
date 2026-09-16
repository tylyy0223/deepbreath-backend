"""add unique constraint (post_id, user_id) to community_likes

Revision ID: e1f2a3b4c5d6
Revises: de7b76e7dd14
Create Date: 2026-09-16 10:17:00

修复点赞竞态: 同一用户对同一帖子只能点赞一次, 防止并发请求产生重复行
"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'de7b76e7dd14'
branch_labels = None
depends_on = None


def upgrade():
    # 先去重: 保留每个 (post_id, user_id) 的最早一行, 删除其余
    # 注意: 必须先做这步, 否则加 unique 约束时会因重复行失败
    op.execute("""
        DELETE FROM community_likes a
        USING community_likes b
        WHERE a.post_id = b.post_id
          AND a.user_id = b.user_id
          AND a.id > b.id
    """)
    op.create_unique_constraint(
        'uq_community_likes_post_user',
        'community_likes',
        ['post_id', 'user_id'],
    )


def downgrade():
    op.drop_constraint('uq_community_likes_post_user', 'community_likes', type_='unique')