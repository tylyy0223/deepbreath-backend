import time, logging
from fastapi import Request

logger = logging.getLogger('timing')

async def timing_middleware(request: Request, call_next):
    t0 = time.time()
    response = await call_next(request)
    dt = (time.time() - t0) * 1000
    if '/api/v1/chat' in str(request.url):
        logger.info(f'[TIMING] {request.method} {request.url.path} -> {dt:.0f}ms')
    return response
