from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Deque

from util.music_queue import (
    QueuedTrack,
    _track_title,
    move_queue_track,
    remove_queue_track,
    shuffle_queue,
)


@dataclass(frozen=True)
class QueueActionResult:
    user_message: str


def _ensure_queue_has_tracks(queue: Deque[QueuedTrack]) -> None:
    if not queue:
        raise ValueError("대기열이 비어있습니다.")


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
