from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class MusicLogger(Protocol):
    def debug(self, message: object, *args: object, **kwargs: object) -> None:
        ...


MusicDebugCallable = Callable[[str], None]


def log_music_debug(logger: MusicLogger, message: str) -> None:
    try:
        logger.debug("[MUSIC] %s", message)
    except (OSError, RuntimeError):
        logger.debug("music debug 출력 실패", exc_info=True)


def make_music_debug_logger(logger: MusicLogger) -> MusicDebugCallable:
    def debug(message: str) -> None:
        log_music_debug(logger, message)

    return debug


def build_music_play_command_debug_message(
    *,
    url: str,
    guild_id: int,
    user_id: int,
) -> str:
    return f"_play: called url={url} guild={guild_id} user={user_id}"
