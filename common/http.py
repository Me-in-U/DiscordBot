import asyncio
import aiohttp


EXTERNAL_HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=30,
    sock_connect=10,
    sock_read=20,
)


async def fetch_text_with_retry(session, url: str, **kwargs) -> str:
    for attempt in range(3):
        delay = 2 ** attempt
        try:
            async with session.get(url, **kwargs) as response:
                response.raise_for_status()
                return await response.text()
        except aiohttp.ClientResponseError as exc:
            if exc.status not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                raise
            retry_after = (exc.headers or {}).get("Retry-After")
            if retry_after is not None:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    raise exc
                if not 0 <= delay <= 30:
                    raise
        except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, asyncio.TimeoutError):
            if attempt == 2:
                raise
        await asyncio.sleep(delay)
