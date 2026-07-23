"""呼吸练习种子数据 — 4 个经典练习（幂等，按 title 判重）

用法: cd /root/deep-breath/backend && venv/bin/python seed_breath.py
"""
import asyncio
import json

from app.core.database import async_session
from app.models.breath import BreathExercise
from sqlalchemy import select

EXERCISES = [
    {
        "title": "盒式呼吸",
        "description": "吸气-屏息-呼气-屏息各 4 秒，像沿着正方形的四条边呼吸。美国海豹突击队用它在高压下保持冷静，适合快速稳定情绪。",
        "technique_type": "box_breathing",
        "duration_sec": 240,
        "animation_config": json.dumps({"inhale": 4, "hold": 4, "exhale": 4, "rest": 4}),
        "sort_order": 1,
    },
    {
        "title": "4-7-8 助眠呼吸",
        "description": "吸气 4 秒、屏息 7 秒、呼气 8 秒。延长的呼气强力激活副交感神经，特别适合睡前和焦虑时使用。",
        "technique_type": "478",
        "duration_sec": 300,
        "animation_config": json.dumps({"inhale": 4, "hold": 7, "exhale": 8, "rest": 0}),
        "sort_order": 2,
    },
    {
        "title": "腹式深呼吸",
        "description": "一只手放腹部，吸气时让腹部像气球一样鼓起，缓慢呼气时收回。最基础也最重要的放松呼吸，随时随地可以练习。",
        "technique_type": "diaphragmatic",
        "duration_sec": 300,
        "animation_config": json.dumps({"inhale": 4, "hold": 2, "exhale": 6, "rest": 1}),
        "sort_order": 3,
    },
    {
        "title": "5-5 平衡呼吸",
        "description": "吸气 5 秒、呼气 5 秒，每分钟约 6 次呼吸。研究表明这个节奏能最大化心率变异性（HRV），长期练习提升压力韧性。",
        "technique_type": "coherent",
        "duration_sec": 360,
        "animation_config": json.dumps({"inhale": 5, "hold": 0, "exhale": 5, "rest": 0}),
        "sort_order": 4,
    },
]


async def seed():
    async with async_session() as db:
        for e in EXERCISES:
            r = await db.execute(select(BreathExercise).where(BreathExercise.title == e["title"]))
            if r.scalar_one_or_none():
                print(f"  练习已存在: {e['title']}")
                continue
            db.add(BreathExercise(**e, status="active"))
            print(f"  创建练习: {e['title']}")
        await db.commit()
        print("呼吸练习种子完成 ✅")


if __name__ == "__main__":
    asyncio.run(seed())
