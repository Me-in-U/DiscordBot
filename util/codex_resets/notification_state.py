from __future__ import annotations

import json
from dataclasses import dataclass

from util.db import execute_query, fetch_one


CODEX_RESET_STATE_KEY_PREFIX = "codexResetNotification"


@dataclass(frozen=True, slots=True)
class CodexResetNotificationState:
    last_tweet_id: str | None = None
    last_announced_at: str | None = None


async def load_codex_reset_notification_state(
    guild_id: int,
) -> CodexResetNotificationState:
    row = await fetch_one(
        "SELECT setting_value FROM setting_data WHERE setting_key = %s",
        (_state_key(guild_id),),
    )
    if not row:
        return CodexResetNotificationState()

    payload = _decode_state_payload(row.get("setting_value"))
    return CodexResetNotificationState(
        last_tweet_id=_optional_text(payload.get("lastTweetId")),
        last_announced_at=_optional_text(payload.get("lastAnnouncedAt")),
    )


async def save_codex_reset_notification_state(
    guild_id: int,
    state: CodexResetNotificationState,
) -> None:
    payload = {
        "lastTweetId": state.last_tweet_id,
        "lastAnnouncedAt": state.last_announced_at,
    }
    await execute_query(
        "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
        (
            _state_key(guild_id),
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def _state_key(guild_id: int) -> str:
    return f"{CODEX_RESET_STATE_KEY_PREFIX}:{int(guild_id)}"


def _decode_state_payload(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
