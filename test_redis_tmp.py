import asyncio
from app.core.redis import redis_client

async def test():
    try:
        await redis_client.delete('test123:key')
        cnt = await redis_client.incr('test123:key')
        print(f'incr ok, cnt={cnt}')
        await redis_client.expire('test123:key', 30)
        print('expire ok')
        print(f'get={await redis_client.get("test123:key")}')
        print(f'ttl={await redis_client.ttl("test123:key")}')
        await redis_client.delete('test123:key')
    except Exception as e:
        print(f'error: {type(e).__name__}: {e}')

asyncio.run(test())