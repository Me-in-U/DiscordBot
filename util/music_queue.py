from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Deque, Optional, Tuple

from yt_dlp.utils import DownloadError


@dataclass
class QueuedTrack:
    """대기열에 URL만 저장하는 경량 트랙."""

    url: str
    requester: Any = None
    title: str | None = None
    duration: int = 0
    webpage_url: str | None = None
    uploader: str | None = None
    thumbnail: str | None = None
    added_at: float = field(default_factory=lambda: time.time())


@dataclass(frozen=True)
class QueueDisplay:
    title: str
    description: str


def parse_seek_seconds(value: str) -> int:
    text = (value or "").strip()
    if not text:
        raise ValueError("시간을 입력해 주세요.")

    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("시간 형식이 올바르지 않습니다.")
        minutes, seconds = (int(parts[0]), int(parts[1]))
        if seconds >= 60:
            raise ValueError("초는 0~59 사이여야 합니다.")
        total = minutes * 60 + seconds
    else:
        if not text.isdigit():
            raise ValueError("시간 형식이 올바르지 않습니다.")
        total = int(text)

    if total < 0:
        raise ValueError("시간은 0초 이상이어야 합니다.")
    return total


def _validate_queue_position(queue: Deque[QueuedTrack], position: int) -> int:
    if position < 1 or position > len(queue):
        raise ValueError(f"대기열 번호는 1~{len(queue)} 사이여야 합니다.")
    return position - 1


def remove_queue_track(queue: Deque[QueuedTrack], position: int) -> QueuedTrack:
    index = _validate_queue_position(queue, position)
    tracks = list(queue)
    removed = tracks.pop(index)
    queue.clear()
    queue.extend(tracks)
    return removed


def move_queue_track(
    queue: Deque[QueuedTrack], current_position: int, new_position: int
) -> QueuedTrack:
    current_index = _validate_queue_position(queue, current_position)
    if new_position < 1 or new_position > len(queue):
        raise ValueError(f"이동 위치는 1~{len(queue)} 사이여야 합니다.")

    tracks = list(queue)
    moved = tracks.pop(current_index)
    tracks.insert(new_position - 1, moved)
    queue.clear()
    queue.extend(tracks)
    return moved


def shuffle_queue(
    queue: Deque[QueuedTrack], randomizer: Optional[random.Random] = None
) -> None:
    tracks = list(queue)
    rng = randomizer or random
    rng.shuffle(tracks)
    queue.clear()
    queue.extend(tracks)


def _track_title(track: QueuedTrack) -> str:
    return track.title or track.webpage_url or track.url or "(제목 정보 없음)"


def build_queue_preview(
    queue: Deque[QueuedTrack],
    *,
    limit: int = 3,
    title_limit: int = 28,
) -> Optional[Tuple[str, str]]:
    if not queue:
        return None

    def _shorten(title: str) -> str:
        if len(title) <= title_limit:
            return title
        return f"{title[:title_limit]}…"

    lines = [
        f"`{index}` {_shorten(_track_title(track))}"
        for index, track in enumerate(list(queue)[:limit], start=1)
    ]
    remaining = len(queue) - limit
    if remaining > 0:
        lines.append(f"+ {remaining}곡 더")
    return f"대기열({len(queue)}개)", "\n".join(lines)


def build_queue_display(
    queue: Deque[QueuedTrack],
    *,
    player: Any = None,
    max_display: int = 10,
    unknown: str = "알 수 없음",
) -> QueueDisplay:
    desc_lines: list[str] = []
    if player is not None and getattr(player, "title", None):
        data = getattr(player, "data", {}) or {}
        minutes, seconds = divmod(int(data.get("duration", 0) or 0), 60)
        uploader = data.get("uploader") or unknown
        requester = _requester_label(getattr(player, "requester", None), unknown)
        desc_lines.append(
            f"**현재 재생 중.** \n"
            f"[{player.title}]({getattr(player, 'webpage_url', None)})"
            f"({minutes:02}:{seconds:02})({uploader}) - 신청자: {requester}"
        )
        desc_lines.append("")

    visible_tracks = list(queue)[:max_display]
    for index, track in enumerate(visible_tracks, start=1):
        minutes, seconds = divmod(int(track.duration or 0), 60)
        uploader = track.uploader or unknown
        requester = _requester_label(track.requester, unknown)
        title = _track_title(track)
        link = track.webpage_url or track.url
        length = f"({minutes:02}:{seconds:02})" if track.duration else ""
        desc_lines.append(
            f"{index}. [{title}]({link}){length}({uploader}) - 신청자: {requester}"
        )

    if len(queue) > max_display:
        desc_lines.append(f"... 외 {len(queue) - max_display}곡")

    return QueueDisplay(
        title=f"대기열 - {len(queue)}개의 곡",
        description="\n".join(desc_lines),
    )


def enqueue_url_track(
    queue: Deque[QueuedTrack],
    url: str,
    requester: Any = None,
) -> QueuedTrack:
    track = QueuedTrack(url=url, requester=requester)
    queue.append(track)
    return track


def enqueue_search_entry_track(
    queue: Deque[QueuedTrack],
    entry: dict[str, Any],
    *,
    url: str,
    requester: Any = None,
) -> QueuedTrack:
    track = QueuedTrack(
        url=url,
        requester=requester,
        title=entry.get("title") or None,
        duration=int(entry.get("duration") or 0) if entry.get("duration") else 0,
        webpage_url=entry.get("webpage_url") or url,
        uploader=entry.get("uploader") or entry.get("channel") or None,
        thumbnail=_search_entry_thumbnail(entry),
    )
    queue.append(track)
    return track


def apply_queue_track_metadata(
    track: QueuedTrack,
    metadata: dict[str, Any],
) -> QueuedTrack:
    info = metadata
    if "entries" in info and info.get("entries"):
        entry = (info.get("entries") or [None])[0]
        if isinstance(entry, dict):
            info = entry

    track.title = info.get("title") or track.title
    track.duration = int(info.get("duration") or 0) or track.duration
    track.webpage_url = info.get("webpage_url") or track.webpage_url or track.url
    track.uploader = info.get("uploader") or track.uploader
    track.thumbnail = info.get("thumbnail") or _search_entry_thumbnail(info) or track.thumbnail
    return track


def extract_queue_track_metadata(
    url: str,
    extractor: Callable[[str], Any],
) -> dict[str, Any] | None:
    try:
        metadata = extractor(url)
    except (DownloadError, OSError, TypeError, ValueError):
        return None
    return metadata if isinstance(metadata, dict) else None


def _search_entry_thumbnail(entry: dict[str, Any]) -> str | None:
    thumbnail = entry.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail:
        return thumbnail

    thumbnails = entry.get("thumbnails") or []
    if isinstance(thumbnails, list) and thumbnails:
        candidate = thumbnails[-1]
        if isinstance(candidate, dict):
            candidate_url = candidate.get("url")
            return candidate_url if isinstance(candidate_url, str) else None

    return None


def _requester_label(requester: Any, unknown: str) -> str:
    requester_id = getattr(requester, "id", None)
    if requester_id is None:
        return unknown
    return f"<@{requester_id}>"
