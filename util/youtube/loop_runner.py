from __future__ import annotations

from typing import Protocol

import aiohttp

from util.youtube.notification_state import touch_pending_youtube_video_check
from util.youtube.subscriptions import (
    YouTubeSubscription,
    get_youtube_subscription,
    list_all_youtube_subscriptions,
)


class YouTubeNotificationOwner(Protocol):
    async def _delete_legacy_youtube_live_checker_setting_once(self) -> None: ...

    async def _poll_youtube_feed_fallback(
        self,
        subscription: YouTubeSubscription,
        session: aiohttp.ClientSession,
    ) -> YouTubeSubscription | None: ...

    async def _remove_pending_youtube_video(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription: ...

    def _should_check_pending_youtube_video(self, pending_entry: dict) -> bool: ...

    async def _process_youtube_video_candidate(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> str: ...


class YouTubeCommunityOwner(Protocol):
    async def _poll_youtube_community_posts(
        self,
        subscription: YouTubeSubscription,
    ) -> YouTubeSubscription: ...


async def run_youtube_notification_candidates(owner: YouTubeNotificationOwner) -> None:
    await owner._delete_legacy_youtube_live_checker_setting_once()
    subscriptions = await list_all_youtube_subscriptions()
    async with aiohttp.ClientSession(trust_env=False) as session:
        for subscription in subscriptions:
            subscription = await owner._poll_youtube_feed_fallback(
                subscription,
                session,
            )
            if subscription is None:
                continue

            pending = dict(subscription.pending_videos)
            if not pending:
                continue

            for video_id, pending_entry in list(pending.items()):
                if not isinstance(pending_entry, dict):
                    subscription = await owner._remove_pending_youtube_video(
                        subscription,
                        str(video_id),
                    )
                    pending = dict(subscription.pending_videos)
                    continue
                if not owner._should_check_pending_youtube_video(pending_entry):
                    continue

                subscription = await touch_pending_youtube_video_check(
                    subscription,
                    str(video_id),
                    pending_entry,
                )
                await owner._process_youtube_video_candidate(
                    subscription,
                    str(video_id),
                )
                refreshed = await get_youtube_subscription(subscription.id)
                if refreshed is None:
                    break
                subscription = refreshed
                pending = dict(subscription.pending_videos)


async def run_youtube_community_posts(owner: YouTubeCommunityOwner) -> None:
    subscriptions = await list_all_youtube_subscriptions()
    for subscription in subscriptions:
        if not subscription.community_alert_enabled:
            continue
        await owner._poll_youtube_community_posts(subscription)
