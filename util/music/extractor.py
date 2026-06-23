from __future__ import annotations

from collections.abc import Sequence
from typing import Any


MusicFormat = dict[str, Any]
MusicInfo = dict[str, Any]


def _rate_key(fmt: MusicFormat) -> tuple[int | float, int | float, int | float]:
    return (fmt.get("abr") or 0, fmt.get("asr") or 0, fmt.get("tbr") or 0)


def select_best_audio_format(formats: Sequence[MusicFormat]) -> MusicFormat | None:
    if not formats:
        return None

    strict_audio = [
        fmt
        for fmt in formats
        if (fmt.get("audio_ext") and fmt.get("audio_ext") != "none")
        and (str(fmt.get("acodec", "none")) != "none")
        and fmt.get("url")
    ]
    loose_audio = [
        fmt
        for fmt in formats
        if str(fmt.get("vcodec", "none")) == "none"
        and fmt.get("url")
        and ((fmt.get("abr") or 0) > 0 or str(fmt.get("acodec", "none")) != "none")
    ]
    candidates = strict_audio or loose_audio or list(formats)
    return max(candidates, key=_rate_key)


def resolve_search_result_url(info: MusicInfo) -> str:
    entries = [entry for entry in (info.get("entries") or []) if entry]
    if not entries:
        raise ValueError("검색 결과가 없습니다.")

    entry = entries[0]
    video_id = entry.get("id")
    url = (
        entry.get("webpage_url")
        or entry.get("url")
        or (f"https://www.youtube.com/watch?v={video_id}" if video_id else None)
    )
    if not url:
        raise ValueError("검색 결과 URL이 없습니다.")
    return str(url)


def select_yt_dlp_entry(data: MusicInfo) -> MusicInfo:
    if "entries" not in data:
        return data

    entries = [entry for entry in (data.get("entries") or []) if entry]
    if not entries:
        return data
    return next((entry for entry in entries if entry.get("formats")), entries[0])
