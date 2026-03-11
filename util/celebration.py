from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import discord
import holidays

from util.channel_settings import get_channel, get_channels_by_purpose
from util.db import execute_query, fetch_all, fetch_one

SEOUL_TZ = timezone(timedelta(hours=9))
CELEBRATION_MESSAGE_PREFIX = "📢 새로운 하루가 시작됩니다."
CELEBRATION_SETTING_KEY_PREFIX = "celebration_message"


@dataclass(slots=True)
class CelebrationUpdateResult:
    guild_id: int
    channel_id: int | None = None
    message_id: int | None = None
    action: str | None = None
    status: str = "ok"
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "guild_id": self.guild_id,
            "status": self.status,
        }
        if self.channel_id is not None:
            data["channel_id"] = self.channel_id
        if self.message_id is not None:
            data["message_id"] = self.message_id
        if self.action is not None:
            data["action"] = self.action
        if self.error is not None:
            data["error"] = self.error
        return data


def _setting_key(guild_id: int) -> str:
    return f"{CELEBRATION_SETTING_KEY_PREFIX}:{int(guild_id)}"


def _normalize_now(target_dt: datetime | None = None) -> datetime:
    if target_dt is None:
        return datetime.now(SEOUL_TZ)
    if target_dt.tzinfo is None:
        return target_dt.replace(tzinfo=SEOUL_TZ)
    return target_dt.astimezone(SEOUL_TZ)


def _decode_setting_value(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


async def _load_tracked_message(guild_id: int) -> dict[str, object] | None:
    query = "SELECT setting_value FROM setting_data WHERE setting_key = %s"
    row = await fetch_one(query, (_setting_key(guild_id),))
    if not row:
        return None
    return _decode_setting_value(row["setting_value"])


async def _save_tracked_message(
    guild_id: int,
    channel_id: int,
    message_id: int,
    target_date: date,
) -> None:
    payload = json.dumps(
        {
            "date": target_date.isoformat(),
            "channel_id": int(channel_id),
            "message_id": int(message_id),
        },
        ensure_ascii=False,
    )
    query = (
        "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = %s"
    )
    key = _setting_key(guild_id)
    await execute_query(query, (key, payload, payload))


async def get_today_celebration_items(
    target_dt: datetime | None = None,
) -> list[str]:
    now = _normalize_now(target_dt)
    today = now.date()
    today_key = today.strftime("%m-%d")

    items: list[str] = []
    holiday_kr = holidays.Korea()
    if today in holiday_kr:
        items.append(f"🇰🇷 한국 공휴일: {holiday_kr[today]}")

    query = "SELECT event_name FROM special_days WHERE day_key = %s ORDER BY event_name ASC"
    rows = await fetch_all(query, (today_key,))
    if rows:
        items.extend(str(row["event_name"]) for row in rows if row.get("event_name"))

    return items


async def build_celebration_message(target_dt: datetime | None = None) -> str:
    items = await get_today_celebration_items(target_dt)
    message = CELEBRATION_MESSAGE_PREFIX
    if items:
        message += "\n### 기념일 및 사건\n- " + "\n- ".join(items)
    return message


async def _resolve_text_channel(
    bot: discord.Client,
    guild_id: int,
    channel_id: int,
) -> discord.TextChannel | None:
    channel = bot.get_channel(int(channel_id))
    if isinstance(channel, discord.TextChannel):
        return channel

    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return None

    try:
        fetched = await guild.fetch_channel(int(channel_id))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None

    return fetched if isinstance(fetched, discord.TextChannel) else None


async def get_celebration_channels(
    bot: discord.Client,
    guild_id: int | None = None,
) -> dict[int, discord.TextChannel]:
    if guild_id is not None:
        channel_id = await get_channel(int(guild_id), "celebration")
        if channel_id is None:
            return {}
        channel = await _resolve_text_channel(bot, int(guild_id), int(channel_id))
        return {int(guild_id): channel} if channel else {}

    celebration_channels = await get_channels_by_purpose("celebration")
    resolved: dict[int, discord.TextChannel] = {}
    for current_guild_id, channel_id in celebration_channels.items():
        channel = await _resolve_text_channel(bot, current_guild_id, channel_id)
        if channel is not None:
            resolved[current_guild_id] = channel
    return resolved


async def _find_existing_celebration_message(
    bot: discord.Client,
    guild_id: int,
    channel: discord.TextChannel,
    target_date: date,
) -> discord.Message | None:
    tracked = await _load_tracked_message(guild_id)
    if tracked and tracked.get("date") == target_date.isoformat():
        message_id = tracked.get("message_id")
        if message_id is not None:
            try:
                message = await channel.fetch_message(int(message_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                message = None
            if (
                message is not None
                and message.author == bot.user
                and message.content.startswith(CELEBRATION_MESSAGE_PREFIX)
            ):
                return message

    start_of_day = datetime.combine(target_date, time.min, tzinfo=SEOUL_TZ)
    async for message in channel.history(
        limit=None,
        after=start_of_day - timedelta(seconds=1),
        oldest_first=False,
    ):
        if message.created_at.astimezone(SEOUL_TZ).date() != target_date:
            continue
        if message.author != bot.user:
            continue
        if not message.content.startswith(CELEBRATION_MESSAGE_PREFIX):
            continue

        await _save_tracked_message(guild_id, channel.id, message.id, target_date)
        return message

    return None


async def refresh_celebration_messages(
    bot: discord.Client,
    guild_id: int | None = None,
) -> list[CelebrationUpdateResult]:
    now = datetime.now(SEOUL_TZ)
    target_date = now.date()
    message = await build_celebration_message(now)

    if guild_id is not None:
        channel_id = await get_channel(int(guild_id), "celebration")
        if channel_id is None:
            return [
                CelebrationUpdateResult(
                    guild_id=int(guild_id),
                    status="error",
                    action="missing_channel",
                    error="기념일 채널이 설정되지 않았습니다.",
                )
            ]

        channel = await _resolve_text_channel(bot, int(guild_id), int(channel_id))
        if channel is None:
            return [
                CelebrationUpdateResult(
                    guild_id=int(guild_id),
                    channel_id=int(channel_id),
                    status="error",
                    action="missing_channel",
                    error="설정된 기념일 채널을 찾을 수 없습니다.",
                )
            ]
        channels = {int(guild_id): channel}
    else:
        channels = await get_celebration_channels(bot)

    results: list[CelebrationUpdateResult] = []
    for current_guild_id, channel in channels.items():
        try:
            existing_message = await _find_existing_celebration_message(
                bot,
                current_guild_id,
                channel,
                target_date,
            )
            if existing_message is None:
                sent_message = await channel.send(message)
                action = "sent"
            else:
                sent_message = await existing_message.edit(content=message)
                action = "edited"

            await _save_tracked_message(
                current_guild_id,
                channel.id,
                sent_message.id,
                target_date,
            )
            results.append(
                CelebrationUpdateResult(
                    guild_id=current_guild_id,
                    channel_id=channel.id,
                    message_id=sent_message.id,
                    action=action,
                )
            )
        except Exception as exc:
            results.append(
                CelebrationUpdateResult(
                    guild_id=current_guild_id,
                    channel_id=channel.id,
                    status="error",
                    error=str(exc),
                )
            )

    return results
