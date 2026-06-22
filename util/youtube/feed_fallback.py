from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import aiohttp

from util.youtube_subscriptions import (
    YouTubeSubscription,
    get_youtube_subscription,
)
from util.youtube.websub import (
    YouTubeAtomEntry,
    build_youtube_feed_topic_url,
    parse_youtube_atom_entries,
    should_process_youtube_feed_update,
)


logger = logging.getLogger(__name__)

ProcessVideoCandidate = Callable[[YouTubeSubscription, str], Awaitable[str]]
FetchFeedEntries = Callable[
    [aiohttp.ClientSession, YouTubeSubscription],
    Awaitable[list[YouTubeAtomEntry]],
]
GetSubscription = Callable[[int], Awaitable[YouTubeSubscription | None]]
LogMessage = Callable[[str], None]


@dataclass(slots=True)
class YouTubeFeedFallbackState:
    checked_at: dict[int, datetime] = field(default_factory=dict)
    seen_updates: dict[int, dict[str, str]] = field(default_factory=dict)


def should_poll_youtube_feed(
    state: YouTubeFeedFallbackState,
    subscription_id: int,
    *,
    now: datetime | None = None,
    interval_seconds: int = 300,
) -> bool:
    current = _current_utc(now)
    last_checked = state.checked_at.get(subscription_id)
    if last_checked and current - last_checked < timedelta(seconds=interval_seconds):
        return False
    state.checked_at[subscription_id] = current
    return True


def remember_youtube_feed_entry_seen(
    state: YouTubeFeedFallbackState,
    subscription_id: int,
    video_id: str,
    entry_updated: str,
    *,
    limit: int = 50,
) -> None:
    seen_updates = state.seen_updates.setdefault(subscription_id, {})
    seen_updates[video_id] = entry_updated
    if len(seen_updates) > limit:
        for old_video_id in list(seen_updates)[: len(seen_updates) - limit]:
            seen_updates.pop(old_video_id, None)


def should_process_youtube_feed_entry(
    state: YouTubeFeedFallbackState,
    subscription: YouTubeSubscription,
    entry: YouTubeAtomEntry,
) -> bool:
    seen_updates = state.seen_updates.setdefault(subscription.id, {})
    return should_process_youtube_feed_update(
        video_id=entry.video_id,
        entry_updated=entry.updated or entry.published,
        seen_updates=seen_updates,
        pending_videos=subscription.pending_videos,
        notified_video_ids=subscription.notified_video_ids,
        notified_upload_video_ids=subscription.notified_upload_video_ids,
    )


async def fetch_youtube_feed_entries(
    session: aiohttp.ClientSession,
    subscription: YouTubeSubscription,
    *,
    log: LogMessage = print,
) -> list[YouTubeAtomEntry]:
    topic_url = build_youtube_feed_topic_url(subscription.channel_id)
    async with session.get(topic_url) as response:
        if response.status < 200 or response.status >= 300:
            body = await response.text()
            log(
                "YouTube Atom feed 조회 실패: "
                f"channel={subscription.channel_id} "
                f"status={response.status} body={body[:300]}"
            )
            return []
        atom_xml = await response.text()
    return parse_youtube_atom_entries(atom_xml)


async def poll_youtube_feed_fallback(
    process_video_candidate: ProcessVideoCandidate,
    state: YouTubeFeedFallbackState,
    subscription: YouTubeSubscription,
    session: aiohttp.ClientSession,
    *,
    fetch_entries: FetchFeedEntries = fetch_youtube_feed_entries,
    get_subscription: GetSubscription = get_youtube_subscription,
    now: datetime | None = None,
    interval_seconds: int = 300,
    max_entries: int = 5,
) -> YouTubeSubscription | None:
    if not should_poll_youtube_feed(
        state,
        subscription.id,
        now=now,
        interval_seconds=interval_seconds,
    ):
        return subscription

    try:
        entries = await fetch_entries(session, subscription)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        logger.warning(
            "YouTube Atom feed 처리 오류: channel=%s",
            subscription.channel_id,
            exc_info=True,
        )
        return subscription

    for entry in entries[:max_entries]:
        if entry.channel_id != subscription.channel_id:
            continue

        if not should_process_youtube_feed_entry(state, subscription, entry):
            continue

        await process_video_candidate(subscription, entry.video_id)
        remember_youtube_feed_entry_seen(
            state,
            subscription.id,
            entry.video_id,
            entry.updated or entry.published,
        )
        refreshed = await get_subscription(subscription.id)
        if refreshed is None:
            return None
        subscription = refreshed

    return subscription


def _current_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)
