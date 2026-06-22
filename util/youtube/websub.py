from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree


YOUTUBE_FEED_BASE_URL = "https://www.youtube.com/feeds/videos.xml"
YOUTUBE_HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
YOUTUBE_SHORTS_MAX_SECONDS = 180

ATOM_NS = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"


class YouTubeVideoStatus(StrEnum):
    LIVE = "live"
    UPCOMING = "upcoming"
    UPLOAD = "upload"
    SHORTS = "shorts"
    NOT_LIVE = "not_live"


@dataclass(frozen=True, slots=True)
class YouTubeAtomEntry:
    video_id: str
    channel_id: str
    title: str
    link: str
    published: str
    updated: str


@dataclass(frozen=True, slots=True)
class YouTubeVideoLiveStatus:
    video_id: str
    channel_id: str
    title: str
    status: YouTubeVideoStatus
    published_at: str | None = None
    scheduled_start_time: str | None = None


def build_youtube_feed_topic_url(channel_id: str) -> str:
    return f"{YOUTUBE_FEED_BASE_URL}?{urlencode({'channel_id': channel_id})}"


def build_youtube_websub_callback_url(callback_url: str, verify_token: str) -> str:
    if not callback_url or not verify_token:
        return callback_url

    split = urlsplit(callback_url)
    query_items = dict(parse_qsl(split.query, keep_blank_values=True))
    query_items.setdefault("token", verify_token)
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(query_items),
            split.fragment,
        )
    )


def build_youtube_websub_request_data(
    *,
    channel_id: str,
    callback_url: str,
    mode: str,
    lease_seconds: int,
) -> dict[str, str]:
    data = {
        "hub.mode": mode,
        "hub.topic": build_youtube_feed_topic_url(channel_id),
        "hub.callback": callback_url,
        "hub.verify": "async",
    }
    if mode == "subscribe":
        data["hub.lease_seconds"] = str(lease_seconds)
    return data


def build_youtube_live_notification_message(video_id: str) -> str:
    return f"## 🔴 [LIVE 시작](https://youtu.be/{video_id})"


def build_youtube_upload_notification_message(
    channel_name: str,
    title: str,
    video_id: str,
) -> str:
    display_channel = channel_name.strip() or "유튜브"
    display_title = title.strip() or "새 영상"
    return f"## 📺 {display_channel} 새 영상\n**{display_title}**\nhttps://youtu.be/{video_id}"


def should_send_youtube_upload_alert(
    *,
    upload_alert_enabled: bool,
    upload_alert_enabled_at: str | None,
    published_at: str | None,
) -> bool:
    if not upload_alert_enabled:
        return False
    enabled_at = _parse_youtube_datetime(upload_alert_enabled_at)
    published = _parse_youtube_datetime(published_at)
    if enabled_at is None or published is None:
        return True
    return published >= enabled_at


def _parse_youtube_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_iso8601_duration_seconds(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value,
    )
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _find_text(element: ElementTree.Element, name: str) -> str:
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def _find_alternate_link(element: ElementTree.Element) -> str:
    for link in element.findall(f"{ATOM_NS}link"):
        if link.attrib.get("rel") == "alternate":
            return link.attrib.get("href", "").strip()
    return ""


def parse_youtube_atom_entries(atom_xml: str) -> list[YouTubeAtomEntry]:
    root = ElementTree.fromstring(atom_xml)
    entries: list[YouTubeAtomEntry] = []

    for entry in root.findall(f"{ATOM_NS}entry"):
        video_id = _find_text(entry, f"{YT_NS}videoId")
        channel_id = _find_text(entry, f"{YT_NS}channelId")
        if not video_id or not channel_id:
            continue

        entries.append(
            YouTubeAtomEntry(
                video_id=video_id,
                channel_id=channel_id,
                title=_find_text(entry, f"{ATOM_NS}title"),
                link=_find_alternate_link(entry),
                published=_find_text(entry, f"{ATOM_NS}published"),
                updated=_find_text(entry, f"{ATOM_NS}updated"),
            )
        )

    return entries


def classify_video_item(item: dict) -> YouTubeVideoLiveStatus:
    snippet = item.get("snippet", {}) or {}
    live_details = item.get("liveStreamingDetails", {}) or {}
    content_details = item.get("contentDetails", {}) or {}

    video_id = str(item.get("id", "") or "")
    channel_id = str(snippet.get("channelId", "") or "")
    title = str(snippet.get("title", "") or "")
    published_at = snippet.get("publishedAt")
    live_broadcast_content = str(snippet.get("liveBroadcastContent", "") or "")

    actual_start_time = live_details.get("actualStartTime")
    actual_end_time = live_details.get("actualEndTime")
    scheduled_start_time = live_details.get("scheduledStartTime")
    duration_seconds = _parse_iso8601_duration_seconds(content_details.get("duration"))

    if actual_start_time and not actual_end_time:
        status = YouTubeVideoStatus.LIVE
    elif live_broadcast_content == "upcoming" or (
        scheduled_start_time and not actual_start_time and not actual_end_time
    ):
        status = YouTubeVideoStatus.UPCOMING
    elif actual_start_time or actual_end_time or scheduled_start_time:
        status = YouTubeVideoStatus.NOT_LIVE
    elif (
        duration_seconds is not None
        and 0 < duration_seconds <= YOUTUBE_SHORTS_MAX_SECONDS
    ):
        status = YouTubeVideoStatus.SHORTS
    else:
        status = YouTubeVideoStatus.UPLOAD

    return YouTubeVideoLiveStatus(
        video_id=video_id,
        channel_id=channel_id,
        title=title,
        status=status,
        published_at=str(published_at) if published_at else None,
        scheduled_start_time=scheduled_start_time,
    )


def should_process_youtube_feed_update(
    *,
    video_id: str,
    entry_updated: str,
    seen_updates: dict[str, str],
    pending_videos: dict[str, Any],
    notified_video_ids: list[str],
    notified_upload_video_ids: list[str] | None = None,
) -> bool:
    notified_ids = {str(current_id) for current_id in notified_video_ids if current_id}
    notified_upload_ids = {
        str(current_id) for current_id in (notified_upload_video_ids or []) if current_id
    }
    if video_id in notified_ids or video_id in notified_upload_ids:
        return False
    if video_id in pending_videos:
        return True
    return seen_updates.get(video_id) != entry_updated
