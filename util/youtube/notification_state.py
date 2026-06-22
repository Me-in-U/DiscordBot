from __future__ import annotations

from collections.abc import Awaitable, Callable
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from util.youtube.subscriptions import (
    YouTubeSubscription,
    update_youtube_subscription_state,
    update_youtube_upload_notification_state,
)
from util.youtube.websub import YouTubeVideoLiveStatus


DEFAULT_PENDING_CHECK_INTERVAL_SECONDS = 300
DEFAULT_PENDING_EARLY_WINDOW = timedelta(minutes=15)
DEFAULT_PENDING_EXPIRE_WINDOW = timedelta(hours=24)
DEFAULT_NOTIFIED_ID_LIMIT = 30

UpdateSubscriptionState = Callable[..., Awaitable[None]]
UpdateUploadNotificationState = Callable[..., Awaitable[None]]


def notified_id_set(values: Iterable[object] | None) -> set[str]:
    if not values:
        return set()
    return {str(value) for value in values if value}


def parse_youtube_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def should_check_pending_youtube_video(
    pending_entry: Mapping[str, Any],
    *,
    now: datetime | None = None,
    check_interval_seconds: int = DEFAULT_PENDING_CHECK_INTERVAL_SECONDS,
    early_window: timedelta = DEFAULT_PENDING_EARLY_WINDOW,
    expire_window: timedelta = DEFAULT_PENDING_EXPIRE_WINDOW,
) -> bool:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    last_checked = parse_youtube_datetime(
        _optional_string(pending_entry.get("lastCheckedAt"))
    )
    if (
        last_checked
        and current - last_checked < timedelta(seconds=check_interval_seconds)
    ):
        return False

    scheduled_start = parse_youtube_datetime(
        _optional_string(pending_entry.get("scheduledStartTime"))
    )
    if scheduled_start is None:
        return True

    return scheduled_start - early_window <= current <= scheduled_start + expire_window


async def mark_youtube_video_notified(
    subscription: YouTubeSubscription,
    video_id: str,
    *,
    update_state: UpdateSubscriptionState = update_youtube_subscription_state,
) -> YouTubeSubscription:
    notified_ids = append_recent_id(subscription.notified_video_ids, video_id)
    pending = remove_pending_video(subscription.pending_videos, video_id)
    await update_state(
        subscription.id,
        pending_videos=pending,
        notified_video_ids=notified_ids,
    )
    return replace(
        subscription,
        pending_videos=pending,
        notified_video_ids=notified_ids,
    )


async def mark_youtube_upload_video_notified(
    subscription: YouTubeSubscription,
    video_id: str,
    *,
    update_upload_state: UpdateUploadNotificationState = (
        update_youtube_upload_notification_state
    ),
) -> YouTubeSubscription:
    notified_ids = append_recent_id(subscription.notified_upload_video_ids, video_id)
    await update_upload_state(
        subscription.id,
        notified_upload_video_ids=notified_ids,
    )
    return replace(subscription, notified_upload_video_ids=notified_ids)


async def remember_pending_youtube_video(
    subscription: YouTubeSubscription,
    status: YouTubeVideoLiveStatus,
    *,
    now: datetime | None = None,
    update_state: UpdateSubscriptionState = update_youtube_subscription_state,
) -> YouTubeSubscription:
    pending = dict(subscription.pending_videos)
    pending[status.video_id] = build_pending_video_entry(status, now=now)
    await update_state(
        subscription.id,
        pending_videos=pending,
        notified_video_ids=subscription.notified_video_ids,
    )
    return replace(subscription, pending_videos=pending)


async def remove_pending_youtube_video(
    subscription: YouTubeSubscription,
    video_id: str,
    *,
    update_state: UpdateSubscriptionState = update_youtube_subscription_state,
) -> YouTubeSubscription:
    pending = remove_pending_video(subscription.pending_videos, video_id)
    await update_state(
        subscription.id,
        pending_videos=pending,
        notified_video_ids=subscription.notified_video_ids,
    )
    return replace(subscription, pending_videos=pending)


async def touch_pending_youtube_video_check(
    subscription: YouTubeSubscription,
    video_id: str,
    pending_entry: Mapping[str, Any],
    *,
    now: datetime | None = None,
    update_state: UpdateSubscriptionState = update_youtube_subscription_state,
) -> YouTubeSubscription:
    pending = dict(subscription.pending_videos)
    pending[str(video_id)] = {
        **dict(pending_entry),
        "lastCheckedAt": _current_utc(now).isoformat(),
    }
    await update_state(
        subscription.id,
        pending_videos=pending,
        notified_video_ids=subscription.notified_video_ids,
    )
    return replace(subscription, pending_videos=pending)


def append_recent_id(
    values: Iterable[object] | None,
    new_id: str,
    *,
    limit: int = DEFAULT_NOTIFIED_ID_LIMIT,
) -> list[str]:
    ids = [str(value) for value in values or [] if value]
    if new_id not in ids:
        ids.append(new_id)
    return ids[-limit:]


def build_pending_video_entry(
    status: YouTubeVideoLiveStatus,
    *,
    now: datetime | None = None,
) -> dict[str, str | None]:
    return {
        "title": status.title,
        "channelId": status.channel_id,
        "scheduledStartTime": status.scheduled_start_time,
        "lastCheckedAt": _current_utc(now).isoformat(),
    }


def remove_pending_video(
    pending_videos: Mapping[str, Any],
    video_id: str,
) -> dict[str, Any]:
    pending = dict(pending_videos)
    pending.pop(video_id, None)
    return pending


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _current_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)
