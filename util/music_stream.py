from __future__ import annotations

import json
import re
from typing import Any


def extract_initial_player_response(html: str) -> dict[str, Any]:
    match = re.search(r"ytInitialPlayerResponse\s*=\s*(\{[^;]+\});", html)
    if not match:
        raise ValueError("ytInitialPlayerResponse not found in page")
    data = json.loads(match.group(1))
    if not isinstance(data, dict):
        raise ValueError("ytInitialPlayerResponse is not an object")
    return data


def select_initial_audio_format(player_response: dict[str, Any]) -> dict[str, Any]:
    adaptive_formats = (
        player_response.get("streamingData", {}).get("adaptiveFormats", []) or []
    )
    audio_formats = [
        fmt
        for fmt in adaptive_formats
        if str(fmt.get("mimeType", "")).startswith("audio/")
    ]
    if not audio_formats:
        raise ValueError("no audio formats in adaptiveFormats")
    return max(audio_formats, key=lambda fmt: fmt.get("averageBitrate", 0))


def build_stream_info_from_player_response(
    player_response: dict[str, Any],
    *,
    page_url: str,
) -> tuple[str, dict[str, Any]]:
    best = select_initial_audio_format(player_response)
    audio_url = best.get("url")

    video_details = player_response.get("videoDetails", {}) or {}
    microformat = player_response.get("microformat", {}) or {}
    renderer = microformat.get("playerMicroformatRenderer", {}) or {}
    thumbnail = _last_thumbnail_url(
        (renderer.get("thumbnail", {}) or {}).get("thumbnails")
        or (video_details.get("thumbnail", {}) or {}).get("thumbnails")
        or []
    )
    data = {
        "title": video_details.get("title"),
        "webpage_url": page_url,
        "duration": int(video_details.get("lengthSeconds", 0) or 0),
        "uploader": video_details.get("author") or renderer.get("ownerChannelName"),
        "thumbnail": thumbnail,
    }
    return audio_url, data


def _last_thumbnail_url(thumbnails: list[dict[str, Any]]) -> str | None:
    if not thumbnails:
        return None
    return thumbnails[-1].get("url")
