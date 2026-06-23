# def_youtube_summary.py
import asyncio
import logging
from dataclasses import dataclass

import aiohttp
from dotenv import load_dotenv
from util.env_utils import getenv_clean, sanitize_environment

from func.youtube_api import (
    YouTubeApiError,
    fetch_video_title as _fetch_youtube_video_title,
)
from func.youtube_links import (
    YOUTUBE_POST_KIND,
    YOUTUBE_VIDEO_KIND,
    extract_post_id,
    extract_video_id,
    extract_youtube_link,
    extract_youtube_links,
    get_youtube_link_kind,
    normalize_youtube_link,
)
from func.youtube_media import download_youtube_subtitles
from func.youtube_post import (
    YouTubePostInfo,
    build_youtube_post_summary_input,
    parse_youtube_post_html,
)
from func.youtube_processor import (
    YouTubeSummaryError,
    fetch_youtube_post,
    process_youtube_link,
    process_youtube_post_link,
    process_youtube_video_link,
)
from func.youtube_summary_ui import (
    YouTubeSummaryView,
    check_youtube_link,
    get_youtube_prompt_text,
    get_youtube_summary_title,
)
from func.youtube_transcript import read_subtitles_file, remove_unnecessary_line_breaks

load_dotenv()
sanitize_environment()
GOOGLE_API_KEY = getenv_clean("GOOGLE_API_KEY")
logger = logging.getLogger(__name__)

if not GOOGLE_API_KEY:
    raise EnvironmentError("GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다.")

@dataclass(slots=True)
class YouTubeLinkCandidate:
    url: str
    link_kind: str
    title: str = ""


def _truncate_display_text(text: str, max_length: int = 80) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def find_recent_youtube_links_in_messages(
    messages, max_links: int = 10
) -> list[tuple[str, str]]:
    found_links: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    for message in messages:
        content = getattr(message, "content", "") or ""
        for youtube_url in extract_youtube_links(content):
            if youtube_url in seen_urls:
                continue

            seen_urls.add(youtube_url)
            link_kind = get_youtube_link_kind(youtube_url) or YOUTUBE_VIDEO_KIND
            found_links.append((youtube_url, link_kind))

            if len(found_links) >= max_links:
                return found_links

    return found_links


def find_latest_youtube_link_in_messages(messages) -> tuple[str, str] | None:
    recent_links = find_recent_youtube_links_in_messages(messages, max_links=1)
    return recent_links[0] if recent_links else None


async def find_latest_youtube_link_in_channel(
    channel, limit: int = 100
) -> tuple[str, str] | None:
    history = getattr(channel, "history", None)
    if history is None:
        return None

    recent_links = await find_recent_youtube_links_in_channel(
        channel, max_links=1, history_limit=limit
    )
    return recent_links[0] if recent_links else None


async def find_recent_youtube_links_in_channel(
    channel, max_links: int = 10, history_limit: int = 200
) -> list[tuple[str, str]]:
    history = getattr(channel, "history", None)
    if history is None:
        return []

    found_links: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    async for message in channel.history(limit=history_limit):
        content = getattr(message, "content", "") or ""
        for youtube_url in extract_youtube_links(content):
            if youtube_url in seen_urls:
                continue

            seen_urls.add(youtube_url)
            link_kind = get_youtube_link_kind(youtube_url) or YOUTUBE_VIDEO_KIND
            found_links.append((youtube_url, link_kind))

            if len(found_links) >= max_links:
                return found_links

    return found_links


def _build_youtube_link_title_fallback(url: str, link_kind: str) -> str:
    if link_kind == YOUTUBE_POST_KIND:
        post_id = extract_post_id(url) or url
        return f"[게시물] {post_id}"

    video_id = extract_video_id(url) or url
    return f"[영상] {video_id}"


async def get_youtube_link_title(url: str, link_kind: str) -> str:
    try:
        if link_kind == YOUTUBE_POST_KIND:
            post_info = await fetch_youtube_post(url)
            preview = _truncate_display_text(
                post_info.text or post_info.author or post_info.post_id,
                max_length=70,
            )
            if post_info.author and preview and preview != post_info.author:
                return _truncate_display_text(
                    f"[게시물] {post_info.author}: {preview}",
                    max_length=100,
                )
            if preview:
                return _truncate_display_text(
                    f"[게시물] {preview}",
                    max_length=100,
                )
            return _build_youtube_link_title_fallback(url, link_kind)

        video_id = extract_video_id(url)
        title = await asyncio.to_thread(_fetch_youtube_video_title, video_id)
        return title or _build_youtube_link_title_fallback(url, link_kind)
    except (aiohttp.ClientError, asyncio.TimeoutError, YouTubeApiError, ValueError):
        logger.warning("YouTube 제목 조회 실패: url=%s", url, exc_info=True)
        return _build_youtube_link_title_fallback(url, link_kind)


async def get_recent_youtube_links_with_titles(
    channel, max_links: int = 10, history_limit: int = 200
) -> list[YouTubeLinkCandidate]:
    recent_links = await find_recent_youtube_links_in_channel(
        channel, max_links=max_links, history_limit=history_limit
    )
    if not recent_links:
        return []

    titles = await asyncio.gather(
        *(get_youtube_link_title(url, link_kind) for url, link_kind in recent_links)
    )
    return [
        YouTubeLinkCandidate(url=url, link_kind=link_kind, title=title)
        for (url, link_kind), title in zip(recent_links, titles, strict=False)
    ]

def is_youtube_link(text: str) -> bool:
    """
    메시지 텍스트에서 유튜브 링크가 있는지 간단히 판별
    """
    return bool(extract_youtube_link(text))
