from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Any, Deque

from util.music_queue import QueuedTrack


@dataclass
class GuildMusicState:
    player: Any = None
    start_ts: float = 0.0
    paused_at: float | None = None
    queue: Deque[QueuedTrack] = field(default_factory=collections.deque)
    control_channel: object | None = None
    control_msg: object | None = None
    control_view: object | None = None
    updater_task: object | None = None
    idle_disconnect_task: object | None = None
    is_loop: bool = False
    is_seeking: bool = False
    is_skipping: bool = False
    is_stopping: bool = False


def reset_music_playback_state(state: GuildMusicState) -> None:
    state.player = None
    state.queue.clear()
    state.is_loop = False
    state.is_skipping = False
    if state.updater_task:
        state.updater_task.cancel()
        state.updater_task = None


def reset_music_idle_state(state: GuildMusicState) -> None:
    state.player = None
    state.paused_at = None
    state.start_ts = 0.0
    state.is_loop = False
    state.is_skipping = False
    state.is_stopping = False


def start_music_playback_state(
    state: GuildMusicState,
    player: Any,
    *,
    started_at: float,
) -> None:
    state.is_stopping = False
    state.is_skipping = False
    state.player = player
    state.start_ts = started_at
    state.paused_at = None


def finish_music_track_state(
    state: GuildMusicState,
    *,
    ended_at: float,
) -> None:
    if state.updater_task:
        state.updater_task.cancel()
    state.paused_at = None
    state.start_ts = ended_at
