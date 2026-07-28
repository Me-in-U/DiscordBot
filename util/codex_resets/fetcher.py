from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp


CODEX_RESETS_API_URL = "https://codex-resets.com/api/resets"
CODEX_RESETS_REQUEST_TIMEOUT_SECONDS = 15
CODEX_RESETS_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "DiscordBot Codex reset notifier",
}
FetchJson = Callable[[], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class CodexResetEvent:
    tweet_id: str
    tweet_url: str
    text: str
    announced_at: datetime


@dataclass(frozen=True, slots=True)
class CodexResetSnapshot:
    events: tuple[CodexResetEvent, ...]
    generated_at: datetime | None = None


def parse_codex_resets_payload(payload: object) -> CodexResetSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("Codex reset response must be an object")

    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("Codex reset response is missing events")

    events: list[CodexResetEvent] = []
    seen_tweet_ids: set[str] = set()
    for raw_event in raw_events:
        event = _parse_codex_reset_event(raw_event)
        if event.tweet_id in seen_tweet_ids:
            continue
        seen_tweet_ids.add(event.tweet_id)
        events.append(event)

    events.sort(key=lambda item: item.announced_at, reverse=True)
    generated_at = _parse_optional_datetime(payload.get("generated_at"))
    return CodexResetSnapshot(
        events=tuple(events),
        generated_at=generated_at,
    )


async def fetch_codex_reset_snapshot(
    *,
    fetch_json: FetchJson | None = None,
) -> CodexResetSnapshot:
    if fetch_json is not None:
        return parse_codex_resets_payload(await fetch_json())

    timeout = aiohttp.ClientTimeout(total=CODEX_RESETS_REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(headers=CODEX_RESETS_HEADERS) as session:
        async with session.get(CODEX_RESETS_API_URL, timeout=timeout) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    return parse_codex_resets_payload(payload)


def _parse_codex_reset_event(raw_event: object) -> CodexResetEvent:
    if not isinstance(raw_event, dict):
        raise ValueError("Codex reset event must be an object")

    tweet_id = _required_text(raw_event, "tweet_id")
    tweet_url = _required_text(raw_event, "tweet_url")
    text = _required_text(raw_event, "text")
    announced_at = _parse_required_datetime(raw_event.get("announced_at"))
    if not tweet_url.startswith(("https://x.com/", "https://twitter.com/")):
        raise ValueError("Codex reset event has an invalid tweet URL")

    return CodexResetEvent(
        tweet_id=tweet_id,
        tweet_url=tweet_url,
        text=text,
        announced_at=announced_at,
    )


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Codex reset event is missing {key}")
    return value.strip()


def _parse_required_datetime(value: object) -> datetime:
    parsed = _parse_optional_datetime(value)
    if parsed is None:
        raise ValueError("Codex reset event has an invalid announced_at")
    return parsed


def _parse_optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
