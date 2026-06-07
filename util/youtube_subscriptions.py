from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from util.db import execute_query, fetch_all, fetch_one


YOUTUBE_LIVE_SETTING_KEY = "youtubeLiveChecker"


@dataclass(frozen=True, slots=True)
class YouTubeSubscription:
    id: int
    guild_id: int
    channel_name: str
    channel_id: str
    channel_handle: str | None
    source_input: str
    websub_subscribed_at: str | None
    websub_lease_seconds: int | None
    pending_videos: dict[str, Any]
    notified_video_ids: list[str]
    live_alert_enabled: bool = True
    upload_alert_enabled: bool = False
    upload_alert_enabled_at: str | None = None
    notified_upload_video_ids: list[str] = field(default_factory=list)
    community_alert_enabled: bool = False
    notified_community_post_ids: list[str] = field(default_factory=list)


def row_to_subscription(row: dict[str, Any]) -> YouTubeSubscription:
    subscribed_at = _optional_datetime_text(row.get("websub_subscribed_at"))
    upload_alert_enabled_at = _optional_datetime_text(row.get("upload_alert_enabled_at"))

    return YouTubeSubscription(
        id=int(row["id"]),
        guild_id=int(row["guild_id"]),
        channel_name=str(row["channel_name"] or row["channel_id"]),
        channel_id=str(row["channel_id"]),
        channel_handle=_optional_text(row.get("channel_handle")),
        source_input=str(row.get("source_input") or row["channel_id"]),
        websub_subscribed_at=subscribed_at,
        websub_lease_seconds=_optional_int(row.get("websub_lease_seconds")),
        pending_videos=_json_dict(row.get("pending_videos")),
        notified_video_ids=_json_string_list(row.get("notified_video_ids")),
        live_alert_enabled=_optional_bool(row.get("live_alert_enabled"), default=True),
        upload_alert_enabled=_optional_bool(
            row.get("upload_alert_enabled"),
            default=False,
        ),
        upload_alert_enabled_at=upload_alert_enabled_at,
        notified_upload_video_ids=_json_string_list(
            row.get("notified_upload_video_ids")
        ),
        community_alert_enabled=_optional_bool(
            row.get("community_alert_enabled"),
            default=False,
        ),
        notified_community_post_ids=_json_string_list(
            row.get("notified_community_post_ids")
        ),
    )


async def list_youtube_subscriptions(guild_id: int) -> list[YouTubeSubscription]:
    query = """
        SELECT *
        FROM youtube_subscriptions
        WHERE guild_id = %s
        ORDER BY channel_name ASC, id ASC
    """
    rows = await fetch_all(query, (int(guild_id),))
    return [row_to_subscription(row) for row in rows]


async def list_all_youtube_subscriptions() -> list[YouTubeSubscription]:
    query = """
        SELECT *
        FROM youtube_subscriptions
        ORDER BY guild_id ASC, channel_name ASC, id ASC
    """
    rows = await fetch_all(query)
    return [row_to_subscription(row) for row in rows]


async def find_youtube_subscriptions_by_channel_id(
    channel_id: str,
) -> list[YouTubeSubscription]:
    query = """
        SELECT *
        FROM youtube_subscriptions
        WHERE channel_id = %s
        ORDER BY guild_id ASC, id ASC
    """
    rows = await fetch_all(query, (channel_id,))
    return [row_to_subscription(row) for row in rows]


async def find_youtube_subscription(
    guild_id: int,
    channel_id: str,
) -> YouTubeSubscription | None:
    query = """
        SELECT *
        FROM youtube_subscriptions
        WHERE guild_id = %s AND channel_id = %s
    """
    row = await fetch_one(query, (int(guild_id), channel_id))
    return row_to_subscription(row) if row else None


async def get_youtube_subscription(subscription_id: int) -> YouTubeSubscription | None:
    query = "SELECT * FROM youtube_subscriptions WHERE id = %s"
    row = await fetch_one(query, (int(subscription_id),))
    return row_to_subscription(row) if row else None


async def create_youtube_subscription(
    *,
    guild_id: int,
    channel_name: str,
    channel_id: str,
    channel_handle: str | None,
    source_input: str,
    live_alert_enabled: bool = True,
    upload_alert_enabled: bool = False,
    community_alert_enabled: bool = False,
    notified_community_post_ids: list[str] | None = None,
) -> int:
    if not live_alert_enabled and not upload_alert_enabled and not community_alert_enabled:
        raise ValueError("라이브 알림, 영상 알림, 커뮤니티 알림 중 하나 이상을 켜야 합니다.")

    existing = await find_youtube_subscription(guild_id, channel_id)
    if existing is not None:
        raise ValueError("이미 등록된 유튜브 채널입니다.")

    upload_alert_enabled_at = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        if upload_alert_enabled
        else None
    )
    query = """
        INSERT INTO youtube_subscriptions (
            guild_id,
            channel_name,
            channel_id,
            channel_handle,
            source_input,
            pending_videos,
            notified_video_ids,
            live_alert_enabled,
            upload_alert_enabled,
            upload_alert_enabled_at,
            notified_upload_video_ids,
            community_alert_enabled,
            notified_community_post_ids
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    initial_post_ids = notified_community_post_ids or []
    return int(
        await execute_query(
            query,
            (
                int(guild_id),
                channel_name,
                channel_id,
                channel_handle,
                source_input,
                "{}",
                "[]",
                bool(live_alert_enabled),
                bool(upload_alert_enabled),
                upload_alert_enabled_at,
                "[]",
                bool(community_alert_enabled),
                json.dumps(initial_post_ids, ensure_ascii=False),
            ),
        )
    )


async def delete_youtube_subscription(
    guild_id: int,
    subscription_id: int,
) -> YouTubeSubscription | None:
    subscription = await get_youtube_subscription(subscription_id)
    if subscription is None or subscription.guild_id != int(guild_id):
        return None

    await execute_query(
        "DELETE FROM youtube_subscriptions WHERE id = %s AND guild_id = %s",
        (int(subscription_id), int(guild_id)),
    )
    return subscription


async def update_youtube_subscription_state(
    subscription_id: int,
    *,
    pending_videos: dict[str, Any],
    notified_video_ids: list[str],
) -> None:
    query = """
        UPDATE youtube_subscriptions
        SET pending_videos = %s,
            notified_video_ids = %s
        WHERE id = %s
    """
    await execute_query(
        query,
        (
            json.dumps(pending_videos, ensure_ascii=False),
            json.dumps(notified_video_ids, ensure_ascii=False),
            int(subscription_id),
        ),
    )


async def update_youtube_upload_notification_state(
    subscription_id: int,
    *,
    notified_upload_video_ids: list[str],
) -> None:
    query = """
        UPDATE youtube_subscriptions
        SET notified_upload_video_ids = %s
        WHERE id = %s
    """
    await execute_query(
        query,
        (
            json.dumps(notified_upload_video_ids, ensure_ascii=False),
            int(subscription_id),
        ),
    )


async def update_youtube_community_notification_state(
    subscription_id: int,
    *,
    notified_community_post_ids: list[str],
) -> None:
    query = """
        UPDATE youtube_subscriptions
        SET notified_community_post_ids = %s
        WHERE id = %s
    """
    await execute_query(
        query,
        (
            json.dumps(notified_community_post_ids, ensure_ascii=False),
            int(subscription_id),
        ),
    )


async def update_youtube_subscription_alert_settings(
    subscription_id: int,
    *,
    live_alert_enabled: bool,
    upload_alert_enabled: bool,
    community_alert_enabled: bool,
) -> YouTubeSubscription | None:
    if not live_alert_enabled and not upload_alert_enabled and not community_alert_enabled:
        raise ValueError("라이브 알림, 영상 알림, 커뮤니티 알림 중 하나 이상을 켜야 합니다.")

    subscription = await get_youtube_subscription(subscription_id)
    if subscription is None:
        return None

    upload_alert_enabled_at = None
    if upload_alert_enabled:
        if subscription.upload_alert_enabled and subscription.upload_alert_enabled_at:
            upload_alert_enabled_at = _parse_db_datetime(
                subscription.upload_alert_enabled_at
            )
        else:
            upload_alert_enabled_at = datetime.now(timezone.utc).replace(tzinfo=None)

    query = """
        UPDATE youtube_subscriptions
        SET live_alert_enabled = %s,
            upload_alert_enabled = %s,
            upload_alert_enabled_at = %s,
            community_alert_enabled = %s
        WHERE id = %s
    """
    await execute_query(
        query,
        (
            bool(live_alert_enabled),
            bool(upload_alert_enabled),
            upload_alert_enabled_at,
            bool(community_alert_enabled),
            int(subscription_id),
        ),
    )
    return await get_youtube_subscription(subscription_id)


async def update_youtube_websub_state(
    subscription_id: int,
    *,
    websub_subscribed_at: datetime,
    websub_lease_seconds: int,
) -> None:
    query = """
        UPDATE youtube_subscriptions
        SET websub_subscribed_at = %s,
            websub_lease_seconds = %s
        WHERE id = %s
    """
    await execute_query(
        query,
        (
            websub_subscribed_at.replace(tzinfo=None),
            int(websub_lease_seconds),
            int(subscription_id),
        ),
    )


async def delete_legacy_youtube_live_checker_setting() -> None:
    await execute_query(
        "DELETE FROM setting_data WHERE setting_key = %s",
        (YOUTUBE_LIVE_SETTING_KEY,),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _optional_datetime_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_db_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return []
