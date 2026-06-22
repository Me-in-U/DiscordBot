from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class YouTubeWebSubRenewalOwner(Protocol):
    async def ensure_youtube_websub_subscription(self) -> bool:
        """Request or refresh YouTube WebSub subscriptions when needed."""


LogFunc = Callable[[str], None]


async def run_youtube_websub_renewal(
    owner: YouTubeWebSubRenewalOwner,
    *,
    log: LogFunc = print,
) -> bool:
    subscribed = await owner.ensure_youtube_websub_subscription()
    if subscribed:
        log("YouTube WebSub 구독 갱신 요청 완료")
    return subscribed
