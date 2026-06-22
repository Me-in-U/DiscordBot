from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from typing import Any


def user_error_message(action: str, exc: BaseException | None = None) -> str:
    """Return a safe user-facing error message for a failed action."""
    normalized_action = str(action or "처리").strip() or "처리"
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
    if root_logger.handlers:
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
