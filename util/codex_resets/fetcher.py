from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from common.http import EXTERNAL_HTTP_TIMEOUT

CODEX_RESETS_API_URL = "https://codex-resets.com/api/v1/resets"
CODEX_RESETS_SITE_URL = "https://codex-resets.com/"
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
    reset_type: str = "regular"


@dataclass(frozen=True, slots=True)
class CodexResetSnapshot:
    events: tuple[CodexResetEvent, ...]
    generated_at: datetime | None = None


def parse_codex_resets_payload(payload: object) -> CodexResetSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("Codex reset response must be an object")

    raw_events = payload.get("data")
    if not isinstance(raw_events, list):
        raise ValueError("Codex reset response is missing data")

    events: list[CodexResetEvent] = []
    seen_tweet_ids: set[str] = set()
    for raw_event in raw_events:
        event = _parse_codex_reset_event(raw_event)
        if event.tweet_id in seen_tweet_ids:
            continue
        seen_tweet_ids.add(event.tweet_id)
        events.append(event)

    events.sort(key=lambda item: item.announced_at, reverse=True)
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("Codex reset response is missing meta")
    generated_at = _parse_optional_datetime(meta.get("generated_at"))
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
    async with aiohttp.ClientSession(
        headers=CODEX_RESETS_HEADERS,
        timeout=EXTERNAL_HTTP_TIMEOUT,
    ) as session:
        # ponytail: latest 100 resets; existing reseeding handles older state.
        async with session.get(
            CODEX_RESETS_API_URL,
            params={"limit": 100, "order": "desc"},
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    return parse_codex_resets_payload(payload)


def _parse_codex_reset_event(raw_event: object) -> CodexResetEvent:
    if not isinstance(raw_event, dict):
        raise ValueError("Codex reset event must be an object")

    # Keep the stored ID format so existing guilds retain their notification state.
    tweet_id = _required_text(raw_event, "id")
    source = raw_event.get("source")
    if not isinstance(source, dict) or source.get("type") not in ("x_post", "observed"):
        raise ValueError("Codex reset event has an invalid source")
    tweet_url = (
        CODEX_RESETS_SITE_URL
        if source.get("type") == "observed" and "url" not in source
        else _required_text(source, "url")
    )
    parsed_url = urlsplit(tweet_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username:
        raise ValueError("Codex reset event has an invalid source URL")
    if source.get("type") == "x_post" and parsed_url.hostname not in ("x.com", "twitter.com"):
        raise ValueError("Codex reset event has an invalid tweet URL")
    reset_type = _required_text(raw_event, "reset_type")
    if reset_type not in ("regular", "banked"):
        raise ValueError("Codex reset event has an invalid reset_type")
    text = _required_text(raw_event, "text")
    announced_at = _parse_required_datetime(raw_event.get("announced_at"))

    return CodexResetEvent(
        tweet_id=tweet_id,
        tweet_url=tweet_url,
        text=text,
        announced_at=announced_at,
        reset_type=reset_type,
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
