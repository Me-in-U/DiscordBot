import aiohttp


EXTERNAL_HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=30,
    sock_connect=10,
    sock_read=20,
)
