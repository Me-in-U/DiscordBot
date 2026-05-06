from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlencode
from xml.etree import ElementTree


YOUTUBE_FEED_BASE_URL = "https://www.youtube.com/feeds/videos.xml"
YOUTUBE_HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"

ATOM_NS = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"


class YouTubeVideoStatus(StrEnum):
    LIVE = "live"
    UPCOMING = "upcoming"
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
    scheduled_start_time: str | None = None


def build_youtube_feed_topic_url(channel_id: str) -> str:
    return f"{YOUTUBE_FEED_BASE_URL}?{urlencode({'channel_id': channel_id})}"


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

    video_id = str(item.get("id", "") or "")
    channel_id = str(snippet.get("channelId", "") or "")
    title = str(snippet.get("title", "") or "")
    live_broadcast_content = str(snippet.get("liveBroadcastContent", "") or "")

    actual_start_time = live_details.get("actualStartTime")
    actual_end_time = live_details.get("actualEndTime")
    scheduled_start_time = live_details.get("scheduledStartTime")

    if actual_start_time and not actual_end_time:
        status = YouTubeVideoStatus.LIVE
    elif live_broadcast_content == "upcoming" or (
        scheduled_start_time and not actual_start_time and not actual_end_time
    ):
        status = YouTubeVideoStatus.UPCOMING
    else:
        status = YouTubeVideoStatus.NOT_LIVE

    return YouTubeVideoLiveStatus(
        video_id=video_id,
        channel_id=channel_id,
        title=title,
        status=status,
        scheduled_start_time=scheduled_start_time,
    )
