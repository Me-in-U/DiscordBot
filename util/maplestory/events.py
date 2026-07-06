from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import discord

from util.maplestory.notice_state import (
    MAPLESTORY_NOTICE_COMPLETED_STATUS,
    MAPLESTORY_NOTICE_STATE_LIMIT,
    MAPLESTORY_NOTICE_PRE_COMPLETION_STATUSES,
    build_maplestory_notice_fingerprint,
    classify_maplestory_notice_maintenance_status,
    find_maplestory_notice_updates,
    find_maplestory_notice_updates_with_state,
    get_latest_maplestory_notice_message_record,
    get_maplestory_notice_maintenance_status,
    get_maplestory_notice_pre_completion_message_records,
    is_maplestory_notice_completion,
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
    edit_maplestory_notice_message,
    resolve_text_channel,
    send_maplestory_notice_to_channel,
    send_sunday_maple_event_to_channels,
)


logger = logging.getLogger(__name__)


MAPLESTORY_NOTICE_CHANNEL_TYPE = "maplestory_notice"
MAPLESTORY_NOTICE_STATE_KEY = "maplestoryNoticeState"
MAPLESTORY_NOTICE_FETCH_LIMIT = 10
MAPLESTORY_NOTICE_LEGACY_HISTORY_SCAN_LIMIT = 50
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
    from util.guild.channel_settings import get_channels_by_purpose

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

        updates, checked_state, migrated = find_maplestory_notice_updates_with_state(
            notices,
            guild_state,
        )
        if migrated:
            guild_states[guild_key] = checked_state
            guild_state = checked_state
            changed = True
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
            cleanup_records = get_maplestory_notice_pre_completion_message_records(
                current_state,
                notice,
                channel_id=channel_id,
            )
            if _should_send_maplestory_notice_without_edit(
                current_state,
                notice,
                channel_id=channel_id,
            ):
                result = await send_maplestory_notice_to_channel(
                    target,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    notice=notice,
                )
            else:
                edit_message = await _find_existing_maplestory_notice_message(
                    target,
                    bot,
                    current_state,
                    notice,
                    channel_id=channel_id,
                )
                if edit_message is None:
                    result = await send_maplestory_notice_to_channel(
                        target,
                        guild_id=guild_id,
                        channel_id=channel_id,
                        notice=notice,
                    )
                else:
                    result = await edit_maplestory_notice_message(
                        edit_message,
                        guild_id=guild_id,
                        channel_id=channel_id,
                        notice=notice,
                    )
                    if result.action == "edit_target_missing":
                        result = await send_maplestory_notice_to_channel(
                            target,
                            guild_id=guild_id,
                            channel_id=channel_id,
                            notice=notice,
                        )
            if result.status != "ok":
                results.append(result)
                continue

            if is_maplestory_notice_completion(notice):
                result.deleted_message_ids = (
                    await _delete_previous_maplestory_maintenance_messages(
                        target,
                        bot,
                        notice,
                        cleanup_records,
                        completion_message_id=result.message_id,
                    )
                )

            _remember_maplestory_notice_in_state(
                current_state,
                notice,
                channel_id=channel_id,
                message_id=result.message_id,
            )
            guild_states[guild_key] = current_state
            changed = True
            results.append(result)

    if changed:
        await _save_maplestory_notice_state(state)

    return results


def _should_send_maplestory_notice_without_edit(
    state: dict[str, Any],
    notice: MapleStoryNotice,
    *,
    channel_id: int,
) -> bool:
    notice_status = get_maplestory_notice_maintenance_status(notice)
    if notice_status == MAPLESTORY_NOTICE_COMPLETED_STATUS:
        return True

    if notice_status != "extended":
        return False

    record = get_latest_maplestory_notice_message_record(
        state,
        notice,
        channel_id=channel_id,
    )
    if record is None:
        return True
    return _maplestory_notice_message_record_status(record) != "extended"


def _maplestory_notice_message_record_status(record: dict[str, Any]) -> str | None:
    status = record.get("status")
    if isinstance(status, str) and status:
        return status

    title = record.get("title")
    if isinstance(title, str):
        return classify_maplestory_notice_maintenance_status("", title)
    return None


async def _find_existing_maplestory_notice_message(
    target: object,
    bot: discord.Client,
    state: dict[str, Any],
    notice: MapleStoryNotice,
    *,
    channel_id: int,
) -> object | None:
    record = get_latest_maplestory_notice_message_record(
        state,
        notice,
        channel_id=channel_id,
    )
    if record is not None:
        message_id = _coerce_int(record.get("messageId"))
        if message_id is not None:
            message = await _fetch_maplestory_notice_message(target, message_id)
            if (
                message is not None
                and _is_editable_maplestory_notice_message(message, bot, notice)
            ):
                return message

    return await _find_legacy_maplestory_notice_message_from_history(
        target,
        bot,
        notice,
    )


async def _find_legacy_maplestory_notice_message_from_history(
    target: object,
    bot: discord.Client,
    notice: MapleStoryNotice,
) -> object | None:
    history = getattr(target, "history", None)
    if not callable(history):
        return None

    try:
        messages = history(limit=MAPLESTORY_NOTICE_LEGACY_HISTORY_SCAN_LIMIT)
        async for message in messages:
            if _is_editable_maplestory_notice_message(message, bot, notice):
                return message
    except (discord.Forbidden, discord.HTTPException):
        logger.warning(
            "메이플스토리 기존 공지 히스토리 조회 실패: notice=%s",
            notice.notice_id,
            exc_info=True,
        )
    return None


def _is_editable_maplestory_notice_message(
    message: object,
    bot: discord.Client,
    notice: MapleStoryNotice,
) -> bool:
    bot_user = getattr(bot, "user", None)
    if bot_user is not None and getattr(message, "author", None) != bot_user:
        return False
    return _message_references_maplestory_notice(message, notice)


def _message_references_maplestory_notice(
    message: object,
    notice: MapleStoryNotice,
) -> bool:
    embeds = getattr(message, "embeds", []) or []
    for embed in embeds:
        if str(getattr(embed, "url", "") or "") == notice.url:
            return True

    content = str(getattr(message, "content", "") or "")
    return notice.url in content


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


async def _delete_previous_maplestory_maintenance_messages(
    target: object,
    bot: discord.Client,
    notice: MapleStoryNotice,
    records: list[dict[str, Any]],
    *,
    completion_message_id: int | None,
) -> list[int]:
    deleted_message_ids: list[int] = []
    checked_message_ids: set[int] = set()

    for record in records:
        message_id = _coerce_int(record.get("messageId"))
        if message_id is None or message_id == completion_message_id:
            continue
        checked_message_ids.add(message_id)
        message = await _fetch_maplestory_notice_message(target, message_id)
        if message is None:
            continue
        if not _is_deletable_maplestory_pre_completion_message(
            message,
            bot,
            notice,
            completion_message_id=completion_message_id,
        ):
            continue
        if await _delete_maplestory_notice_message(message):
            deleted_message_ids.append(message_id)

    history_deleted = await _delete_legacy_maplestory_maintenance_messages_from_history(
        target,
        bot,
        notice,
        checked_message_ids=checked_message_ids,
        completion_message_id=completion_message_id,
    )
    already_deleted = set(deleted_message_ids)
    deleted_message_ids.extend(
        message_id
        for message_id in history_deleted
        if message_id not in already_deleted
    )
    return deleted_message_ids


async def _fetch_maplestory_notice_message(
    target: object,
    message_id: int,
) -> object | None:
    fetch_message = getattr(target, "fetch_message", None)
    if not callable(fetch_message):
        return None
    try:
        return await fetch_message(int(message_id))
    except (discord.NotFound, ValueError, TypeError):
        return None
    except (discord.Forbidden, discord.HTTPException):
        logger.warning(
            "메이플스토리 이전 점검 공지 메시지 조회 실패: message=%s",
            message_id,
            exc_info=True,
        )
        return None


async def _delete_legacy_maplestory_maintenance_messages_from_history(
    target: object,
    bot: discord.Client,
    notice: MapleStoryNotice,
    *,
    checked_message_ids: set[int],
    completion_message_id: int | None,
) -> list[int]:
    history = getattr(target, "history", None)
    if not callable(history):
        return []

    deleted_message_ids: list[int] = []
    try:
        messages = history(limit=MAPLESTORY_NOTICE_LEGACY_HISTORY_SCAN_LIMIT)
        async for message in messages:
            message_id = _coerce_int(getattr(message, "id", None))
            if message_id is None:
                continue
            if message_id in checked_message_ids or message_id == completion_message_id:
                continue
            if not _is_deletable_maplestory_pre_completion_message(
                message,
                bot,
                notice,
                completion_message_id=completion_message_id,
            ):
                continue
            if await _delete_maplestory_notice_message(message):
                deleted_message_ids.append(message_id)
    except (discord.Forbidden, discord.HTTPException):
        logger.warning(
            "메이플스토리 이전 점검 공지 히스토리 조회 실패: notice=%s",
            notice.notice_id,
            exc_info=True,
        )
    return deleted_message_ids


def _is_deletable_maplestory_pre_completion_message(
    message: object,
    bot: discord.Client,
    notice: MapleStoryNotice,
    *,
    completion_message_id: int | None,
) -> bool:
    message_id = _coerce_int(getattr(message, "id", None))
    if message_id is not None and message_id == completion_message_id:
        return False

    bot_user = getattr(bot, "user", None)
    if bot_user is not None and getattr(message, "author", None) != bot_user:
        return False

    return _message_references_pre_completion_maplestory_notice(message, notice)


def _message_references_pre_completion_maplestory_notice(
    message: object,
    notice: MapleStoryNotice,
) -> bool:
    embeds = getattr(message, "embeds", []) or []
    for embed in embeds:
        if str(getattr(embed, "url", "") or "") != notice.url:
            continue
        title = str(getattr(embed, "title", "") or "")
        category = _maplestory_notice_embed_field_value(embed, "분류")
        status = classify_maplestory_notice_maintenance_status(category, title)
        if status in MAPLESTORY_NOTICE_PRE_COMPLETION_STATUSES:
            return True

    content = str(getattr(message, "content", "") or "")
    if notice.url in content:
        status = classify_maplestory_notice_maintenance_status("", content)
        return status in MAPLESTORY_NOTICE_PRE_COMPLETION_STATUSES
    return False


def _maplestory_notice_embed_field_value(embed: object, field_name: str) -> str:
    fields = getattr(embed, "fields", []) or []
    for field in fields:
        if getattr(field, "name", None) == field_name:
            return str(getattr(field, "value", "") or "")
    return ""


async def _delete_maplestory_notice_message(message: object) -> bool:
    try:
        await message.delete()
        return True
    except discord.NotFound:
        return False
    except (discord.Forbidden, discord.HTTPException):
        logger.warning(
            "메이플스토리 이전 점검 공지 메시지 삭제 실패: message=%s",
            getattr(message, "id", None),
            exc_info=True,
        )
        return False


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
