from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from googleapiclient.discovery import build

from util.env_utils import getenv_clean


CHANNEL_ID_PATTERN = re.compile(r"^UC[\w-]{22}$")


@dataclass(frozen=True, slots=True)
class YouTubeChannelMetadata:
    channel_id: str
    channel_name: str
    channel_handle: str | None = None


def is_youtube_channel_id(value: str) -> bool:
    return bool(CHANNEL_ID_PATTERN.fullmatch((value or "").strip()))


def extract_youtube_channel_id(value: str) -> str | None:
    clean_value = (value or "").strip()
    if is_youtube_channel_id(clean_value):
        return clean_value

    split = urlsplit(clean_value)
    path = split.path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "channel" and is_youtube_channel_id(parts[1]):
        return parts[1]
    return None


def extract_youtube_channel_handle(value: str) -> str | None:
    clean_value = (value or "").strip()
    if not clean_value:
        return None
    if clean_value.startswith("@"):
        return clean_value.split("/", 1)[0].split("?", 1)[0]

    split = urlsplit(clean_value)
    for part in split.path.split("/"):
        if part.startswith("@"):
            return part.split("?", 1)[0]
    return None


async def resolve_youtube_channel_input(
    value: str,
    *,
    youtube_client=None,
) -> YouTubeChannelMetadata:
    clean_value = (value or "").strip()
    if not clean_value:
        raise ValueError("유튜브 채널 입력값은 비어 있을 수 없습니다.")

    client = youtube_client or _build_youtube_client()
    channel_id = extract_youtube_channel_id(clean_value)
    if channel_id:
        return await _fetch_channel_metadata(client, id=channel_id)

    handle = extract_youtube_channel_handle(clean_value)
    if handle:
        return await _fetch_channel_metadata(client, forHandle=handle)

    searched_channel_id = await _search_relevant_channel_id(client, clean_value)
    return await _fetch_channel_metadata(client, id=searched_channel_id)


def _build_youtube_client():
    api_key = getenv_clean("GOOGLE_API_KEY")
    return build("youtube", "v3", developerKey=api_key)


async def _fetch_channel_metadata(client, **query) -> YouTubeChannelMetadata:
    def _execute():
        return (
            client.channels()
            .list(part="snippet", maxResults=1, **query)
            .execute()
        )

    response = await asyncio.to_thread(_execute)
    items = response.get("items", []) if isinstance(response, dict) else []
    if not items:
        raise ValueError("유튜브 채널을 찾지 못했습니다.")

    item = items[0]
    snippet = item.get("snippet", {}) or {}
    channel_id = str(item.get("id") or "")
    if not is_youtube_channel_id(channel_id):
        raise ValueError("유효한 유튜브 채널 ID를 가져오지 못했습니다.")

    channel_name = str(snippet.get("title") or channel_id).strip() or channel_id
    channel_handle = str(snippet.get("customUrl") or "").strip() or None
    return YouTubeChannelMetadata(
        channel_id=channel_id,
        channel_name=channel_name,
        channel_handle=channel_handle,
    )


async def _search_relevant_channel_id(client, query: str) -> str:
    def _execute():
        return (
            client.search()
            .list(
                part="snippet",
                q=query,
                type="channel",
                order="relevance",
                maxResults=1,
            )
            .execute()
        )

    response = await asyncio.to_thread(_execute)
    items = response.get("items", []) if isinstance(response, dict) else []
    if not items:
        raise ValueError("유튜브 채널을 찾지 못했습니다.")

    item = items[0]
    item_id = item.get("id", {}) or {}
    channel_id = str(item_id.get("channelId") or "").strip()
    if not is_youtube_channel_id(channel_id):
        raise ValueError("유효한 유튜브 채널 ID를 가져오지 못했습니다.")
    return channel_id
