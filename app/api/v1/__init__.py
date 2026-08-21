from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

# 各模块路由将在后续注册
# from app.api.v1 import auth, chat, content, breath, diary, community, scales, tts, admin
