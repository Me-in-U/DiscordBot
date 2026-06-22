from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import aiohttp


YOUTUBE_COMMUNITY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Mode": "navigate",
}


@dataclass(frozen=True, slots=True)
class YouTubeCommunityPost:
    post_id: str
    url: str
    author: str = ""
    published_time: str = ""
    text: str = ""
    attachment_urls: list[str] = field(default_factory=list)


def build_youtube_community_posts_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}/posts"


def build_youtube_community_post_url(post_id: str) -> str:
    return f"https://youtube.com/post/{post_id}"


def parse_youtube_community_posts_html(html: str) -> list[YouTubeCommunityPost]:
    initial_data = _extract_json_object_after(html, "var ytInitialData = ")
    posts: list[YouTubeCommunityPost] = []
    seen_post_ids: set[str] = set()

    for post_data in _find_renderer_values(initial_data, "backstagePostRenderer"):
        post_id = str(post_data.get("postId") or "").strip()
        if not post_id or post_id in seen_post_ids:
            continue

        seen_post_ids.add(post_id)
        posts.append(
            YouTubeCommunityPost(
                post_id=post_id,
                url=build_youtube_community_post_url(post_id),
                author=_get_text_from_runs(post_data.get("authorText")),
                published_time=_get_text_from_runs(post_data.get("publishedTimeText")),
                text=_get_text_from_runs(post_data.get("contentText")),
                attachment_urls=_collect_attachment_urls(
                    post_data.get("backstageAttachment")
                ),
            )
        )

    return posts


async def fetch_latest_youtube_community_posts(
    channel_id: str,
    limit: int = 10,
) -> list[YouTubeCommunityPost]:
    url = build_youtube_community_posts_url(channel_id)
    async with aiohttp.ClientSession(
        headers=YOUTUBE_COMMUNITY_HEADERS,
        trust_env=False,
    ) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            html = await response.text()

    posts = await asyncio.to_thread(parse_youtube_community_posts_html, html)
    return posts[:limit]


def find_new_youtube_community_posts(
    posts: list[YouTubeCommunityPost],
    notified_post_ids: list[str],
) -> list[YouTubeCommunityPost]:
    notified = {str(post_id) for post_id in notified_post_ids if post_id}
    return [post for post in posts if post.post_id not in notified]


def trim_notified_community_post_ids(
    notified_post_ids: list[str],
    limit: int = 30,
) -> list[str]:
    return [str(post_id) for post_id in notified_post_ids if post_id][-limit:]


def _extract_json_object_after(text: str, marker: str) -> dict:
    marker_index = text.find(marker)
    if marker_index == -1:
        raise ValueError(f"{marker} marker not found")

    start_index = text.find("{", marker_index)
    if start_index == -1:
        raise ValueError(f"{marker} JSON start not found")

    depth = 0
    in_string = False
    escaped = False

    for index in range(start_index, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start_index : index + 1])

    raise ValueError(f"{marker} JSON end not found")


def _find_renderer_values(data: Any, renderer_key: str):
    stack = [data]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            renderer = current.get(renderer_key)
            if isinstance(renderer, dict):
                yield renderer
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def _get_text_from_runs(data: dict | None) -> str:
    if not isinstance(data, dict):
        return ""
    simple_text = data.get("simpleText")
    if isinstance(simple_text, str):
        return simple_text.strip()

    parts = []
    for run in data.get("runs", []):
        text = run.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts).strip()


def _normalize_thumbnail_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _best_thumbnail_url(thumbnails: list[dict]) -> str:
    valid_thumbnails = [thumb for thumb in thumbnails if thumb.get("url")]
    if not valid_thumbnails:
        return ""

    best = max(
        valid_thumbnails,
        key=lambda thumb: thumb.get("width", 0) * thumb.get("height", 0),
    )
    return _normalize_thumbnail_url(best["url"])


def _collect_attachment_urls(attachment) -> list[str]:
    if not attachment:
        return []

    urls = []
    seen = set()
    stack = [attachment]

    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            thumbnails = current.get("thumbnails")
            if isinstance(thumbnails, list):
                thumbnail_url = _best_thumbnail_url(thumbnails)
                if thumbnail_url and thumbnail_url not in seen:
                    seen.add(thumbnail_url)
                    urls.append(thumbnail_url)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)

    return urls
