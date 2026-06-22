from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import aiohttp

from util.youtube.subscriptions import (
    YouTubeSubscription,
    get_youtube_subscription,
    list_all_youtube_subscriptions,
    update_youtube_websub_state,
)
from util.youtube.websub import (
    YOUTUBE_HUB_URL,
    build_youtube_websub_callback_url,
    build_youtube_websub_request_data,
)


DEFAULT_WEBSUB_LEASE_SECONDS = 604800

ListSubscriptions = Callable[[], Awaitable[list[YouTubeSubscription]]]
GetSubscription = Callable[[int], Awaitable[YouTubeSubscription | None]]
RequestSubscription = Callable[..., Awaitable[bool]]
UpdateWebSubState = Callable[..., Awaitable[None]]
LogMessage = Callable[[str], None]


def build_configured_youtube_websub_callback_url(
    callback_url: str,
    verify_token: str,
) -> str:
    callback_url = callback_url.strip()
    verify_token = verify_token.strip()
    if not callback_url:
        return ""
    if not verify_token:
        return callback_url
    return build_youtube_websub_callback_url(callback_url, verify_token)


async def ensure_youtube_websub_subscription(
    *,
    callback_url: str,
    subscription_id: int | None = None,
    list_subscriptions: ListSubscriptions = list_all_youtube_subscriptions,
    get_subscription: GetSubscription = get_youtube_subscription,
    request_subscription: RequestSubscription | None = None,
    update_websub_state: UpdateWebSubState = update_youtube_websub_state,
    now: datetime | None = None,
    lease_seconds: int = DEFAULT_WEBSUB_LEASE_SECONDS,
) -> bool:
    if not callback_url:
        return False

    request_subscription = request_subscription or request_youtube_websub_subscription
    subscriptions = await _load_target_subscriptions(
        subscription_id,
        list_subscriptions=list_subscriptions,
        get_subscription=get_subscription,
    )
    subscriptions = [
        subscription
        for subscription in subscriptions
        if subscription.live_alert_enabled or subscription.upload_alert_enabled
    ]
    if not subscriptions:
        return True

    success_count = 0
    subscribed_at = _current_utc(now)
    for subscription in subscriptions:
        subscribed = await request_subscription(
            subscription,
            callback_url=callback_url,
            mode="subscribe",
        )
        if not subscribed:
            continue
        success_count += 1
        await update_websub_state(
            subscription.id,
            websub_subscribed_at=subscribed_at,
            websub_lease_seconds=lease_seconds,
        )
    return success_count == len(subscriptions)


async def unsubscribe_youtube_websub_subscription(
    subscription: YouTubeSubscription,
    *,
    callback_url: str,
    request_subscription: RequestSubscription | None = None,
) -> bool:
    if not callback_url:
        return False
    request_subscription = request_subscription or request_youtube_websub_subscription
    return await request_subscription(
        subscription,
        callback_url=callback_url,
        mode="unsubscribe",
    )


async def request_youtube_websub_subscription(
    subscription: YouTubeSubscription,
    *,
    callback_url: str,
    mode: str,
    session_factory=aiohttp.ClientSession,
    hub_url: str = YOUTUBE_HUB_URL,
    lease_seconds: int = DEFAULT_WEBSUB_LEASE_SECONDS,
    log: LogMessage = print,
) -> bool:
    data = build_youtube_websub_request_data(
        channel_id=subscription.channel_id,
        callback_url=callback_url,
        mode=mode,
        lease_seconds=lease_seconds,
    )

    async with session_factory(trust_env=False) as session:
        async with session.post(hub_url, data=data) as response:
            if response.status < 200 or response.status >= 300:
                body = await response.text()
                log(
                    "YouTube WebSub 요청 실패: "
                    f"mode={mode} channel={subscription.channel_id} "
                    f"status={response.status} body={body}"
                )
                return False
    return True


async def _load_target_subscriptions(
    subscription_id: int | None,
    *,
    list_subscriptions: ListSubscriptions,
    get_subscription: GetSubscription,
) -> list[YouTubeSubscription]:
    if subscription_id is None:
        return await list_subscriptions()

    subscription = await get_subscription(subscription_id)
    return [subscription] if subscription is not None else []


def _current_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)
