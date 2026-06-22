from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import logging
from typing import Protocol

import aiohttp

from util.youtube_community import (
    YouTubeCommunityPost,
    fetch_latest_youtube_community_posts,
)
from util.youtube.community_notification import (
    process_youtube_community_notifications,
)
from util.youtube_subscriptions import YouTubeSubscription


LogWarning = Callable[..., None]


class FetchCommunityPosts(Protocol):
    def __call__(
        self,
        channel_id: str,
        *,
        limit: int = 10,
    ) -> Awaitable[Sequence[YouTubeCommunityPost]]: ...


class ProcessCommunityNotifications(Protocol):
    def __call__(
        self,
        bot,
        subscription: YouTubeSubscription,
        posts: Sequence[YouTubeCommunityPost],
    ) -> Awaitable[YouTubeSubscription]: ...

logger = logging.getLogger(__name__)


async def poll_youtube_community_posts(
    bot,
    subscription: YouTubeSubscription,
    *,
    fetch_posts: FetchCommunityPosts = fetch_latest_youtube_community_posts,
    process_notifications: ProcessCommunityNotifications = (
        process_youtube_community_notifications
    ),
    log_warning: LogWarning = logger.warning,
) -> YouTubeSubscription:
    if not subscription.community_alert_enabled:
        return subscription

    try:
        posts = await fetch_posts(subscription.channel_id, limit=10)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        log_warning(
            "YouTube 커뮤니티 게시물 조회 실패: channel=%s",
            subscription.channel_id,
            exc_info=True,
        )
        return subscription

    return await process_notifications(bot, subscription, posts)
