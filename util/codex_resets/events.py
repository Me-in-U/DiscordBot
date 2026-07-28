from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import aiohttp
import discord

from util.codex_resets.fetcher import (
    CodexResetEvent,
    CodexResetSnapshot,
    fetch_codex_reset_snapshot,
)
from util.codex_resets.notification_state import (
    CodexResetNotificationState,
    load_codex_reset_notification_state,
    save_codex_reset_notification_state,
)
from util.codex_resets.sender import send_codex_reset_notification


CODEX_RESET_CHANNEL_TYPE = "codex_reset"
logger = logging.getLogger(__name__)

FetchSnapshot = Callable[[], Awaitable[CodexResetSnapshot]]
GetChannels = Callable[[], Awaitable[dict[int, int]]]
LoadState = Callable[[int], Awaitable[CodexResetNotificationState]]
SaveState = Callable[[int, CodexResetNotificationState], Awaitable[None]]
ResolveChannel = Callable[[object, int], Awaitable[object | None]]
SendNotification = Callable[[object, CodexResetEvent], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class CodexResetNotificationResult:
    guild_id: int
    channel_id: int | None = None
    tweet_id: str | None = None
    message_id: int | None = None
    status: str = "ok"
    action: str | None = None
    error: str | None = None


async def seed_codex_reset_state_for_guild(
    guild_id: int,
    *,
    fetch_snapshot: FetchSnapshot | None = None,
    save_state: SaveState | None = None,
) -> int:
    fetch = fetch_snapshot or fetch_codex_reset_snapshot
    save = save_state or save_codex_reset_notification_state
    snapshot = await fetch()
    if not snapshot.events:
        return 0
    await save(guild_id, _state_from_event(snapshot.events[0]))
    return 1


async def refresh_codex_reset_notifications(
    bot: object,
    *,
    get_channels: GetChannels | None = None,
    fetch_snapshot: FetchSnapshot | None = None,
    load_state: LoadState | None = None,
    save_state: SaveState | None = None,
    resolve_channel: ResolveChannel | None = None,
    send_notification: SendNotification | None = None,
) -> list[CodexResetNotificationResult]:
    get_configured_channels = get_channels or _get_codex_reset_channels
    channels = await get_configured_channels()
    if not channels:
        return []

    fetch = fetch_snapshot or fetch_codex_reset_snapshot
    try:
        snapshot = await fetch()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("Codex 리셋 정보 조회 실패", exc_info=True)
        return [
            CodexResetNotificationResult(
                guild_id=guild_id,
                channel_id=channel_id,
                status="error",
                action="fetch_failed",
                error=str(exc),
            )
            for guild_id, channel_id in channels.items()
        ]

    if not snapshot.events:
        return [
            CodexResetNotificationResult(
                guild_id=guild_id,
                channel_id=channel_id,
                status="skipped",
                action="no_events",
            )
            for guild_id, channel_id in channels.items()
        ]

    load = load_state or load_codex_reset_notification_state
    save = save_state or save_codex_reset_notification_state
    resolve = resolve_channel or resolve_codex_reset_channel
    send = send_notification or send_codex_reset_notification
    results: list[CodexResetNotificationResult] = []

    for guild_id, channel_id in channels.items():
        try:
            state = await load(guild_id)
        except Exception as exc:
            logger.warning(
                "Codex 리셋 상태 조회 실패: guild=%s",
                guild_id,
                exc_info=True,
            )
            results.append(
                CodexResetNotificationResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    status="error",
                    action="state_load_failed",
                    error=str(exc),
                )
            )
            continue

        unseen_events, state_is_known = _find_unseen_events(
            snapshot.events,
            state.last_tweet_id,
        )
        if state.last_tweet_id is None or not state_is_known:
            action = (
                "seeded"
                if state.last_tweet_id is None
                else "state_reseeded"
            )
            try:
                await save(guild_id, _state_from_event(snapshot.events[0]))
            except Exception as exc:
                logger.warning(
                    "Codex 리셋 상태 초기화 실패: guild=%s",
                    guild_id,
                    exc_info=True,
                )
                results.append(
                    CodexResetNotificationResult(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        tweet_id=snapshot.events[0].tweet_id,
                        status="error",
                        action="state_seed_failed",
                        error=str(exc),
                    )
                )
                continue
            results.append(
                CodexResetNotificationResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    tweet_id=snapshot.events[0].tweet_id,
                    status="skipped",
                    action=action,
                )
            )
            continue

        if not unseen_events:
            results.append(
                CodexResetNotificationResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    status="skipped",
                    action="no_updates",
                )
            )
            continue

        target = await resolve(bot, channel_id)
        if target is None:
            results.append(
                CodexResetNotificationResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    status="error",
                    action="missing_channel",
                    error="configured channel could not be resolved",
                )
            )
            continue

        for event in unseen_events:
            try:
                message_id = await send(target, event)
            except Exception as exc:
                logger.warning(
                    "Codex 리셋 알림 전송 실패: guild=%s channel=%s tweet=%s",
                    guild_id,
                    channel_id,
                    event.tweet_id,
                    exc_info=True,
                )
                results.append(
                    CodexResetNotificationResult(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        tweet_id=event.tweet_id,
                        status="error",
                        action="send_failed",
                        error=str(exc),
                    )
                )
                break

            try:
                await save(guild_id, _state_from_event(event))
            except Exception as exc:
                logger.warning(
                    "Codex 리셋 전송 상태 저장 실패: guild=%s tweet=%s",
                    guild_id,
                    event.tweet_id,
                    exc_info=True,
                )
                results.append(
                    CodexResetNotificationResult(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        tweet_id=event.tweet_id,
                        message_id=message_id,
                        status="error",
                        action="state_save_failed",
                        error=str(exc),
                    )
                )
                break

            results.append(
                CodexResetNotificationResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    tweet_id=event.tweet_id,
                    message_id=message_id,
                    action="sent",
                )
            )

    return results


async def resolve_codex_reset_channel(
    bot: object,
    channel_id: int,
) -> object | None:
    target = bot.get_channel(int(channel_id))
    if target is None:
        try:
            target = await bot.fetch_channel(int(channel_id))
        except discord.DiscordException:
            return None
    if not hasattr(target, "send"):
        return None
    return target


async def _get_codex_reset_channels() -> dict[int, int]:
    from util.guild.channel_settings import get_channels_by_purpose

    return await get_channels_by_purpose(CODEX_RESET_CHANNEL_TYPE)


def _find_unseen_events(
    events: tuple[CodexResetEvent, ...],
    last_tweet_id: str | None,
) -> tuple[tuple[CodexResetEvent, ...], bool]:
    if last_tweet_id is None:
        return (), False
    for index, event in enumerate(events):
        if event.tweet_id == last_tweet_id:
            return tuple(reversed(events[:index])), True
    return (), False


def _state_from_event(event: CodexResetEvent) -> CodexResetNotificationState:
    return CodexResetNotificationState(
        last_tweet_id=event.tweet_id,
        last_announced_at=event.announced_at.isoformat(),
    )
