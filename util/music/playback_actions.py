from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from util.music.queue import enqueue_url_track
from util.music.queue_actions import QUEUE_ADDED_MESSAGE
from util.music_state import GuildMusicState


@dataclass(frozen=True)
class PlaybackActionResult:
    user_message: str
    elapsed: int = 0
    is_loop: bool | None = None
    delete_after: float | None = None


@dataclass(frozen=True)
class UrlPlayActionResult:
    should_prepare: bool
    user_message: str | None = None
    queued_track: Any | None = None
    queue_size: int = 0


def pause_playback_action(
    state: GuildMusicState,
    *,
    paused_at: float,
) -> PlaybackActionResult:
    state.paused_at = paused_at
    return PlaybackActionResult(
        user_message="⏸️ 일시정지했습니다.",
        elapsed=int(paused_at - state.start_ts),
    )


def resume_playback_action(
    state: GuildMusicState,
    *,
    resumed_at: float,
) -> PlaybackActionResult:
    if state.paused_at:
        state.start_ts += resumed_at - state.paused_at
        state.paused_at = None
    return PlaybackActionResult(
        user_message="▶️ 다시 재생합니다.",
        elapsed=int(resumed_at - state.start_ts),
    )


def begin_stop_playback_action(state: GuildMusicState) -> PlaybackActionResult:
    state.is_stopping = True
    return PlaybackActionResult(user_message="⏹️ 정지하고 나갑니다.")


def begin_url_play_action(
    state: GuildMusicState,
    *,
    url: str,
    requester: Any,
    is_active: bool,
) -> UrlPlayActionResult:
    if not is_active:
        return UrlPlayActionResult(should_prepare=True)

    track = enqueue_url_track(state.queue, url, requester)
    return UrlPlayActionResult(
        should_prepare=False,
        user_message=QUEUE_ADDED_MESSAGE,
        queued_track=track,
        queue_size=len(state.queue),
    )


def begin_play_url_now_playback_action(
    state: GuildMusicState,
    *,
    replacing: bool,
) -> None:
    state.is_stopping = False
    state.is_skipping = False
    if replacing:
        state.is_seeking = True


def complete_play_url_now_playback_action(
    state: GuildMusicState,
    *,
    replacing: bool,
) -> None:
    if replacing:
        state.is_seeking = False


def skip_playback_action(state: GuildMusicState) -> PlaybackActionResult:
    return PlaybackActionResult(
        user_message=(
            "🔁 반복 모드: 처음부터 재생합니다."
            if state.is_loop
            else "⏭️ 스킵합니다."
        ),
        is_loop=state.is_loop,
    )


def validate_seek_playback_action(
    state: GuildMusicState,
    *,
    seconds: int,
) -> PlaybackActionResult | None:
    total = int(state.player.data.get("duration", 0) or 0)
    if total and seconds >= total:
        return PlaybackActionResult(
            user_message=f"❌ 이동할 시간은 곡 길이({total}초)보다 작아야 합니다.",
            delete_after=6.0,
        )
    return None


def begin_seek_playback_action(state: GuildMusicState) -> None:
    state.is_seeking = True


def complete_seek_playback_action(
    state: GuildMusicState,
    player: Any,
    *,
    seconds: int,
    started_at: float,
) -> PlaybackActionResult:
    state.player = player
    state.start_ts = started_at - seconds
    state.paused_at = None
    state.is_seeking = False
    return PlaybackActionResult(
        user_message=f"⏩ {seconds}초 지점으로 이동했습니다.",
        elapsed=seconds,
    )


def fail_seek_playback_action(state: GuildMusicState) -> PlaybackActionResult:
    state.is_seeking = False
    return PlaybackActionResult(
        user_message="❌ 구간 이동 중 오류가 발생했습니다.",
        delete_after=6.0,
    )


def toggle_loop_action(state: GuildMusicState) -> PlaybackActionResult:
    state.is_loop = not state.is_loop
    return PlaybackActionResult(
        user_message=f"🔁 반복 모드 {'켜짐' if state.is_loop else '꺼짐'}",
        is_loop=state.is_loop,
    )
