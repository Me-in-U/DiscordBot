from __future__ import annotations

import logging
import sys
import time
from collections.abc import Mapping
from typing import Any


NOISY_LOGGER_LEVELS = {
    "discord.ext.voice_recv.gateway": logging.WARNING,
    "discord.ext.voice_recv.reader": logging.WARNING,
    "aiohttp.access": logging.WARNING,
    "httpx": logging.WARNING,
}

KST_OFFSET_SECONDS = 9 * 60 * 60


class KoreaStandardTimeFormatter(logging.Formatter):
    """Format log timestamps in Korea Standard Time regardless of host TZ."""

    converter = staticmethod(
        lambda timestamp: time.gmtime(timestamp + KST_OFFSET_SECONDS)
    )


def _iter_exception_chain(exc: BaseException | None):
    seen: set[int] = set()
    pending = [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue

        seen.add(id(current))
        yield current
        pending.extend(
            cause
            for cause in (
                getattr(current, "__cause__", None),
                getattr(current, "__context__", None),
            )
            if cause is not None
        )


def _is_openai_error(exc: BaseException | None) -> bool:
    for current in _iter_exception_chain(exc):
        error_class = current.__class__
        module_name = getattr(error_class, "__module__", "")
        class_name = getattr(error_class, "__name__", "")
        if module_name == "api.chatGPT" and class_name == "OpenAIModelError":
            return True
        if module_name == "openai" or module_name.startswith("openai."):
            return True

    return False


def user_error_message(action: str, exc: BaseException | None = None) -> str:
    """Return a safe user-facing error message for a failed action."""
    normalized_action = str(action or "처리").strip() or "처리"
    if _is_openai_error(exc):
        return f"⚠️ {normalized_action} 중 오류가 발생했습니다. 관리자에게 연락해주세요."
    return f"⚠️ {normalized_action} 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


def log_user_error(
    logger: logging.Logger,
    action: str,
    exc: BaseException | None = None,
    *,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Log an exception with stack details and return a safe Discord message."""
    normalized_action = str(action or "처리").strip() or "처리"
    logger.exception(
        "%s 중 오류가 발생했습니다.",
        normalized_action,
        extra=extra,
    )
    return user_error_message(action, exc)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure process-wide console logging once."""
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            KoreaStandardTimeFormatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s"
            )
        )
        root_logger.addHandler(handler)
        root_logger.setLevel(level)

    for logger_name, logger_level in NOISY_LOGGER_LEVELS.items():
        logging.getLogger(logger_name).setLevel(logger_level)
