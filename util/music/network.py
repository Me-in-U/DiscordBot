import asyncio
from weakref import WeakKeyDictionary
from urllib.parse import urlparse, urlunparse

_slots_by_loop = WeakKeyDictionary()


def validate_music_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"} or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("YouTube 링크만 재생할 수 있습니다.")
    return urlunparse(parsed._replace(scheme="https"))


async def run_extraction(func, executor=None):
    loop = asyncio.get_running_loop()
    slots = _slots_by_loop.setdefault(loop, asyncio.BoundedSemaphore(2))
    await asyncio.wait_for(slots.acquire(), timeout=3)
    try:
        future = asyncio.get_running_loop().run_in_executor(executor, func)
    except BaseException:
        slots.release()
        raise
    future.add_done_callback(lambda _: slots.release())
    return await asyncio.wait_for(asyncio.shield(future), timeout=25)
