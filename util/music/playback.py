from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


STREAM_PREPARE_ERROR_MESSAGE = (
    "❌ 스트림 URL을 가져오지 못했습니다. 잠시 후 다시 시도하거나 다른 영상으로 시도해 주세요."
)
FFMPEG_MISSING_MESSAGE = "❌ FFmpeg 실행 파일을 찾을 수 없습니다."
FFMPEG_MISSING_GUIDANCE_MESSAGE = (
    "❌ FFmpeg 실행 파일을 찾을 수 없습니다.\n"
    "- bin/ffmpeg.exe를 다운로드해 배치하거나,\n"
    "- ffmpeg를 시스템 PATH에 추가한 뒤 다시 시도해 주세요."
)


@dataclass(frozen=True)
class MusicPlayerPreparationFailure:
    user_message: str
    delete_after: float
    debug_message: str


@dataclass(frozen=True)
class MusicReplaySourceResult:
    source: Any
    refreshed_player: Any | None = None


@dataclass(frozen=True)
class PreparedPlaybackStart:
    source: Any
    confirmation_message: str


class MusicPlayerPreparationError(Exception):
    def __init__(
        self,
        failure: MusicPlayerPreparationFailure,
        original_error: BaseException,
    ):
        super().__init__(failure.debug_message)
        self.failure = failure
        self.original_error = original_error


async def prepare_music_player(
    source_factory: Callable[..., Awaitable[Any]],
    url: str,
    *,
    loop: Any,
    requester: Any,
    include_ffmpeg_guidance: bool = False,
    **source_kwargs: Any,
) -> Any:
    try:
        return await source_factory(
            url,
            loop=loop,
            requester=requester,
            **source_kwargs,
        )
    except FileNotFoundError as exc:
        raise MusicPlayerPreparationError(
            _ffmpeg_failure(include_guidance=include_ffmpeg_guidance),
            exc,
        ) from exc
    except Exception as exc:
        raise MusicPlayerPreparationError(
            MusicPlayerPreparationFailure(
                user_message=STREAM_PREPARE_ERROR_MESSAGE,
                delete_after=10.0,
                debug_message=f"source prepare failed: {type(exc).__name__}: {exc}",
            ),
            exc,
        ) from exc


def build_prepared_playback_start(
    player: Any,
    *,
    success_prefix: str = "▶ 재생",
) -> PreparedPlaybackStart:
    return PreparedPlaybackStart(
        source=player.source,
        confirmation_message=f"{success_prefix}: **{player.title}**",
    )


def _ffmpeg_failure(*, include_guidance: bool) -> MusicPlayerPreparationFailure:
    return MusicPlayerPreparationFailure(
        user_message=(
            FFMPEG_MISSING_GUIDANCE_MESSAGE
            if include_guidance
            else FFMPEG_MISSING_MESSAGE
        ),
        delete_after=12.0 if include_guidance else 8.0,
        debug_message="ffmpeg not found",
    )


async def prepare_replay_source(
    player: Any,
    *,
    source_factory: Callable[..., Awaitable[Any]],
    ffmpeg_source_factory: Callable[..., Any],
    ffmpeg_options: dict[str, Any],
    ffmpeg_executable: str,
    loop: Any,
) -> MusicReplaySourceResult:
    audio_url = getattr(player, "audio_url", None) or player.data.get("url")
    try:
        return MusicReplaySourceResult(
            source=ffmpeg_source_factory(
                audio_url,
                **ffmpeg_options,
                executable=ffmpeg_executable,
            )
        )
    except Exception:
        refreshed = await prepare_music_player(
            source_factory,
            player.webpage_url,
            loop=loop,
            requester=None,
        )
        return MusicReplaySourceResult(
            source=refreshed.source,
            refreshed_player=refreshed,
        )
