from __future__ import annotations

import asyncio
from collections.abc import Iterable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchResultsDisplay:
    title: str
    description: str


@dataclass(frozen=True)
class MusicSearchActionResult:
    videos: list[dict[str, Any]]
    embed_title: str | None = None
    embed_description: str | None = None
    user_message: str | None = None


def is_http_url(value: Any) -> bool:
    return isinstance(value, str) and (
        value.startswith("http://") or value.startswith("https://")
    )


def normalize_search_entry_url(entry: dict[str, Any]) -> str:
    raw_url = entry.get("webpage_url") or entry.get("url") or ""
    if isinstance(raw_url, str) and raw_url.startswith("/watch"):
        return f"https://www.youtube.com{raw_url}"
    return raw_url if isinstance(raw_url, str) else ""


def filter_youtube_watch_entries(
    entries: Iterable[Any],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if isinstance(url, str) and "watch?v=" in url:
            videos.append(entry)
            if len(videos) >= limit:
                break
    return videos


def build_search_results_display(
    query: str,
    videos: Iterable[dict[str, Any]],
) -> SearchResultsDisplay:
    lines: list[str] = []
    for index, video in enumerate(videos, start=1):
        title = video.get("title") or "-"
        lines.append(f"{index}. {title}")

    return SearchResultsDisplay(
        title=f"🔍 `{query}` 검색 결과",
        description="\n".join(lines),
    )


def build_music_search_action(
    query: str,
    info: dict[str, Any],
    *,
    favorite_slot: int | None = None,
    limit: int = 10,
) -> MusicSearchActionResult:
    raw_entries = info.get("entries", []) or []
    videos = filter_youtube_watch_entries(raw_entries, limit=limit)
    if not videos:
        return MusicSearchActionResult(
            videos=[],
            user_message="❌ 검색 결과가 없습니다.",
        )

    if favorite_slot is not None:
        description = "\n".join(
            f"{index}. {video.get('title') or '-'}"
            for index, video in enumerate(videos, start=1)
        )
        return MusicSearchActionResult(
            videos=videos,
            embed_title=f"⭐ {favorite_slot}번 즐겨찾기에 저장할 음악 선택",
            embed_description=description,
        )

    display = build_search_results_display(query, videos)
    return MusicSearchActionResult(
        videos=videos,
        embed_title=display.title,
        embed_description=display.description,
    )


async def run_music_search_query(
    query: str,
    extractor: Any,
    *,
    executor: Executor | None = None,
) -> Any:
    def _extract() -> Any:
        search = f"ytsearch10:{query}"
        if callable(extractor):
            return extractor(search)
        return extractor.extract_info(search, download=False)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor,
        _extract,
    )
