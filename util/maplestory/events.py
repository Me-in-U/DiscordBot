from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import discord

from util.maplestory.notice_state import (
    MAPLESTORY_NOTICE_STATE_LIMIT,
    build_maplestory_notice_fingerprint,
    find_maplestory_notice_updates,
    maplestory_notice_state_from_notices,
    normalize_maplestory_notice_state as _normalize_maplestory_notice_state,
    remember_maplestory_notice_in_state as _remember_maplestory_notice_in_state,
)
from util.maplestory.fetcher import (
    FetchHtml,
    MAPLESTORY_HEADERS,
    fetch_latest_maplestory_notices,
    fetch_sunday_maple_event,
)
from util.maplestory.parser import (
    MAPLESTORY_BASE_URL,
    MAPLESTORY_NOTICE_LIST_URL,
    MAPLESTORY_ONGOING_EVENT_LIST_URL,
    SUNDAY_MAPLE_EVENT_TITLE,
    MapleStoryEvent,
    MapleStoryNotice,
    parse_maplestory_event_detail,
    parse_maplestory_notice_detail,
    parse_maplestory_notice_list,
    parse_maplestory_ongoing_event_url,
)
from util.maplestory.sender import (
    MapleStoryNoticeUpdateResult,
    SundayMapleUpdateResult,
    build_maplestory_notice_embed,
    build_maplestory_notice_message,
    build_sunday_maple_event_embeds,
    resolve_text_channel,
    send_maplestory_notice_to_channel,
    send_sunday_maple_event_to_channels,
)


logger = logging.getLogger(__name__)


MAPLESTORY_NOTICE_CHANNEL_TYPE = "maplestory_notice"
MAPLESTORY_NOTICE_STATE_KEY = "maplestoryNoticeState"
MAPLESTORY_NOTICE_FETCH_LIMIT = 10
FetchEvent = Callable[[], Awaitable["MapleStoryEvent | None"]]
FetchNotices = Callable[[], Awaitable[list["MapleStoryNotice"]]]


async def refresh_sunday_maple_messages(
    bot: discord.Client,
    guild_id: int | None = None,
    *,
    fetch_event: FetchEvent | None = None,
) -> list[SundayMapleUpdateResult]:
    from util.celebration.announcements import get_celebration_channels

    channels = await get_celebration_channels(bot, guild_id)
    if not channels:
        return []

    fetch = fetch_event or fetch_sunday_maple_event
    try:
        event = await fetch()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("썬데이메이플 이벤트 조회 실패", exc_info=True)
        return [
            SundayMapleUpdateResult(
                guild_id=current_guild_id,
                channel_id=channel.id,
                status="error",
                action="fetch_failed",
                error=str(exc),
            )
            for current_guild_id, channel in channels.items()
        ]

    if event is None:
        return [
            SundayMapleUpdateResult(
                guild_id=current_guild_id,
                channel_id=channel.id,
                status="skipped",
                action="event_absent",
            )
            for current_guild_id, channel in channels.items()
        ]

    return await send_sunday_maple_event_to_channels(channels, event)


async def refresh_maplestory_notice_messages(
    bot: discord.Client,
    *,
    fetch_notices: FetchNotices | None = None,
) -> list[MapleStoryNoticeUpdateResult]:
    from util.channel_settings import get_channels_by_purpose

    channels = await get_channels_by_purpose(MAPLESTORY_NOTICE_CHANNEL_TYPE)
    if not channels:
        return []

    fetch = fetch_notices or fetch_latest_maplestory_notices
    try:
        notices = await fetch()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("메이플스토리 공지 목록 조회 실패", exc_info=True)
        return [
            MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                status="error",
                action="fetch_failed",
                error=str(exc),
            )
            for guild_id, channel_id in channels.items()
        ]

    state = await _load_maplestory_notice_state()
    changed = False
    results: list[MapleStoryNoticeUpdateResult] = []

    for guild_id, channel_id in channels.items():
        guild_key = str(guild_id)
        guild_states = state.setdefault("guilds", {})
        if not isinstance(guild_states, dict):
            guild_states = {}
            state["guilds"] = guild_states

        guild_state = guild_states.get(guild_key)
        if guild_state is None:
            guild_states[guild_key] = maplestory_notice_state_from_notices(notices)
            changed = True
            results.append(
                MapleStoryNoticeUpdateResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    action="seeded",
                    status="skipped",
                )
            )
            continue

        updates = find_maplestory_notice_updates(notices, guild_state)
        if not updates:
            results.append(
                MapleStoryNoticeUpdateResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    action="unchanged",
                    status="skipped",
                )
            )
            continue

        target = await resolve_text_channel(bot, channel_id)
        if target is None:
            results.append(
                MapleStoryNoticeUpdateResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    status="error",
                    action="channel_missing",
                    error="configured channel was not found",
                )
            )
            continue

        current_state = _normalize_maplestory_notice_state(guild_state)
        for notice in reversed(updates):
            result = await send_maplestory_notice_to_channel(
                target,
                guild_id=guild_id,
                channel_id=channel_id,
                notice=notice,
            )
            if result.status != "ok":
                results.append(result)
                continue

            _remember_maplestory_notice_in_state(current_state, notice)
            guild_states[guild_key] = current_state
            changed = True
            results.append(result)

    if changed:
        await _save_maplestory_notice_state(state)

    return results


async def seed_maplestory_notice_state_for_guild(
    guild_id: int,
    *,
    fetch_notices: FetchNotices | None = None,
) -> int:
    fetch = fetch_notices or fetch_latest_maplestory_notices
    notices = await fetch()
    state = await _load_maplestory_notice_state()
    guild_states = state.setdefault("guilds", {})
    if not isinstance(guild_states, dict):
        guild_states = {}
        state["guilds"] = guild_states
    guild_states[str(int(guild_id))] = maplestory_notice_state_from_notices(notices)
    await _save_maplestory_notice_state(state)
    return len(notices)


async def _load_maplestory_notice_state() -> dict[str, Any]:
    from util.db import fetch_one

    row = await fetch_one(
        "SELECT setting_value FROM setting_data WHERE setting_key = %s",
        (MAPLESTORY_NOTICE_STATE_KEY,),
    )
    if not row:
        return {"guilds": {}}
    value = row.get("setting_value")
    if isinstance(value, dict):
        state = value
    elif isinstance(value, str) and value.strip():
        try:
            state = json.loads(value)
        except json.JSONDecodeError:
            state = {}
    else:
        state = {}
    guilds = state.get("guilds") if isinstance(state, dict) else None
    return {"guilds": guilds if isinstance(guilds, dict) else {}}


async def _save_maplestory_notice_state(state: dict[str, Any]) -> None:
    from util.db import execute_query

    await execute_query(
        "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
        (
            MAPLESTORY_NOTICE_STATE_KEY,
            json.dumps(state, ensure_ascii=False),
        ),
    )
