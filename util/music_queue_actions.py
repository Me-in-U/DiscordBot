from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Deque

from util.music_queue import (
    QueuedTrack,
    _track_title,
    enqueue_search_entry_track,
    move_queue_track,
    remove_queue_track,
    shuffle_queue,
)
from util.music_search import normalize_search_entry_url


QUEUE_ADDED_MESSAGE = "▶ **대기열에 추가되었습니다.**"


@dataclass(frozen=True)
class QueueActionResult:
    user_message: str


@dataclass(frozen=True)
class SearchPickQueueActionResult:
    url: str
    should_play_now: bool
    user_message: str | None = None
    queued_track: QueuedTrack | None = None
    queue_size: int = 0


def _ensure_queue_has_tracks(queue: Deque[QueuedTrack]) -> None:
    if not queue:
        raise ValueError("대기열이 비어있습니다.")


def begin_search_pick_queue_action(
    queue: Deque[QueuedTrack],
    entry: dict[str, Any],
    *,
    requester: Any = None,
    is_active: bool,
) -> SearchPickQueueActionResult:
    url = normalize_search_entry_url(entry)
    if not is_active:
        return SearchPickQueueActionResult(url=url, should_play_now=True)

    track = enqueue_search_entry_track(
        queue,
        entry,
        url=url,
        requester=requester,
    )
    return SearchPickQueueActionResult(
        url=url,
        should_play_now=False,
        user_message=QUEUE_ADDED_MESSAGE,
        queued_track=track,
        queue_size=len(queue),
    )


def remove_queue_action(
    queue: Deque[QueuedTrack],
    position: int,
) -> QueueActionResult:
    _ensure_queue_has_tracks(queue)
    removed = remove_queue_track(queue, position)
    return QueueActionResult(
        user_message=f"🗑️ 대기열에서 **{_track_title(removed)}** 항목을 삭제했습니다."
    )


def clear_queue_action(queue: Deque[QueuedTrack]) -> QueueActionResult:
    _ensure_queue_has_tracks(queue)
    count = len(queue)
    queue.clear()
    return QueueActionResult(user_message=f"🧹 대기열 {count}곡을 비웠습니다.")


def move_queue_action(
    queue: Deque[QueuedTrack],
    current_position: int,
    new_position: int,
) -> QueueActionResult:
    _ensure_queue_has_tracks(queue)
    moved = move_queue_track(queue, current_position, new_position)
    return QueueActionResult(
        user_message=f"↕️ **{_track_title(moved)}** 항목을 {new_position}번으로 이동했습니다."
    )


def shuffle_queue_action(
    queue: Deque[QueuedTrack],
    *,
    shuffler: Callable[[Deque[QueuedTrack]], None] = shuffle_queue,
) -> QueueActionResult:
    if len(queue) < 2:
        raise ValueError("섞을 대기열이 2곡 이상 필요합니다.")
    shuffler(queue)
    return QueueActionResult(user_message="🔀 대기열을 섞었습니다.")
