from __future__ import annotations

import json
from dataclasses import dataclass, field

from func.youtube_links import extract_post_id


@dataclass(slots=True)
class YouTubePostInfo:
    post_id: str
    url: str
    author: str = ""
    published_time: str = ""
    like_count: str = ""
    text: str = ""
    attachment_urls: list[str] = field(default_factory=list)


def parse_youtube_post_html(html: str, url: str) -> YouTubePostInfo:
    initial_data = _extract_json_object_after(html, "var ytInitialData = ")
    post_data = _find_first_key_value(initial_data, "backstagePostRenderer")
    if not isinstance(post_data, dict):
        raise ValueError("유튜브 게시물 정보를 찾지 못했습니다.")

    return YouTubePostInfo(
        post_id=post_data.get("postId") or extract_post_id(url),
        url=url,
        author=_get_text_from_runs(post_data.get("authorText")),
        published_time=_get_text_from_runs(post_data.get("publishedTimeText")),
        like_count=_get_vote_count_text(post_data.get("voteCount")),
        text=_get_text_from_runs(post_data.get("contentText")),
        attachment_urls=_collect_attachment_urls(post_data.get("backstageAttachment")),
    )


def build_youtube_post_summary_input(post_info: YouTubePostInfo) -> str:
    lines = [
        f"게시물 링크: {post_info.url}",
        f"작성자: {post_info.author or '알 수 없음'}",
        f"게시 시각: {post_info.published_time or '알 수 없음'}",
        f"좋아요: {post_info.like_count or '알 수 없음'}",
        "",
        "[본문]",
        post_info.text or "(본문 없음)",
    ]

    if post_info.attachment_urls:
        lines.extend(
            [
                "",
                f"[첨부 이미지 수] {len(post_info.attachment_urls)}",
                *post_info.attachment_urls[:4],
            ]
        )

    return "\n".join(lines).strip()


def _normalize_thumbnail_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    return url


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


def _get_vote_count_text(vote_count: dict | None) -> str:
    text = _get_text_from_runs(vote_count)
    if text:
        return text

    accessibility = (vote_count or {}).get("accessibility", {})
    accessibility_data = accessibility.get("accessibilityData", {})
    return str(accessibility_data.get("label", "")).strip()


def _find_first_key_value(data, target_key: str):
    stack = [data]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if target_key in current:
                return current[target_key]
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return None


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
