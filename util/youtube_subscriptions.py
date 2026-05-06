from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
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


def row_to_subscription(row: dict[str, Any]) -> YouTubeSubscription:
    subscribed_at = row.get("websub_subscribed_at")
    if isinstance(subscribed_at, datetime):
        subscribed_at = subscribed_at.isoformat()
    elif subscribed_at is not None:
        subscribed_at = str(subscribed_at)

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
) -> int:
    existing = await find_youtube_subscription(guild_id, channel_id)
    if existing is not None:
        raise ValueError("이미 등록된 유튜브 채널입니다.")

    query = """
        INSERT INTO youtube_subscriptions (
            guild_id,
            channel_name,
            channel_id,
            channel_handle,
            source_input,
            pending_videos,
            notified_video_ids
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
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
