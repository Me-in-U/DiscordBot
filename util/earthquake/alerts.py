from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import discord

from util.earthquake.jma_eew import (
    JMA_EEW_MIN_MAGNITUDE,
    JmaEewEvent,
    is_recent_jma_eew,
)
from util.earthquake.state import (
    EarthquakeAlertState,
    find_jma_eew_record,
    load_earthquake_alert_state,
    remember_jma_eew_message,
    reset_earthquake_alert_state,
    save_earthquake_alert_state,
)


EARTHQUAKE_ALERT_CHANNEL_TYPE = "earthquake_alert"
logger = logging.getLogger(__name__)

GetChannels = Callable[[], Awaitable[dict[int, int]]]
LoadState = Callable[[int], Awaitable[EarthquakeAlertState]]
SaveState = Callable[[int, EarthquakeAlertState], Awaitable[None]]
ResolveChannel = Callable[[object, int], Awaitable[object | None]]
SendAlert = Callable[[object, JmaEewEvent], Awaitable[int | None]]
EditAlert = Callable[[object, int, JmaEewEvent], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class EarthquakeAlertResult:
    guild_id: int
    channel_id: int | None = None
    event_id: str | None = None
    serial: int | None = None
    message_id: int | None = None
    status: str = "ok"
    action: str | None = None
    error: str | None = None


async def process_jma_eew_event(
    bot: object,
    event: JmaEewEvent,
    *,
    get_channels: GetChannels | None = None,
    load_state: LoadState | None = None,
    save_state: SaveState | None = None,
    resolve_channel: ResolveChannel | None = None,
    send_alert: SendAlert | None = None,
    edit_alert: EditAlert | None = None,
) -> list[EarthquakeAlertResult]:
    get_configured_channels = get_channels or _get_earthquake_alert_channels
    channels = await get_configured_channels()
    if not channels:
        return []

    if event.is_training:
        return [
            EarthquakeAlertResult(
                guild_id=guild_id,
                channel_id=channel_id,
                event_id=event.event_id,
                serial=event.serial,
                status="skipped",
                action="training",
            )
            for guild_id, channel_id in channels.items()
        ]

    load = load_state or load_earthquake_alert_state
    save = save_state or save_earthquake_alert_state
    resolve = resolve_channel or resolve_earthquake_alert_channel
    send = send_alert or send_jma_eew_alert
    edit = edit_alert or edit_jma_eew_alert
    results: list[EarthquakeAlertResult] = []

    for guild_id, channel_id in channels.items():
        try:
            state = await load(guild_id)
        except Exception as exc:
            logger.warning(
                "일본 EEW 상태 조회 실패: guild=%s",
                guild_id,
                exc_info=True,
            )
            results.append(
                _error_result(
                    guild_id,
                    channel_id,
                    event,
                    "state_load_failed",
                    exc,
                )
            )
            continue

        if state.channel_id != int(channel_id):
            state = reset_earthquake_alert_state(channel_id)

        record = find_jma_eew_record(state, event.event_id)
        if record is not None and event.serial <= record.serial:
            results.append(
                _skipped_result(
                    guild_id,
                    channel_id,
                    event,
                    "already_processed",
                )
            )
            continue

        if record is None:
            if event.is_cancelled:
                results.append(
                    _skipped_result(
                        guild_id,
                        channel_id,
                        event,
                        "untracked_cancel",
                    )
                )
                continue
            if not event.is_at_least_magnitude(JMA_EEW_MIN_MAGNITUDE):
                results.append(
                    _skipped_result(
                        guild_id,
                        channel_id,
                        event,
                        "below_threshold",
                    )
                )
                continue
            if not is_recent_jma_eew(event):
                results.append(
                    _skipped_result(
                        guild_id,
                        channel_id,
                        event,
                        "stale",
                    )
                )
                continue

        target = await resolve(bot, channel_id)
        if target is None:
            results.append(
                EarthquakeAlertResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    event_id=event.event_id,
                    serial=event.serial,
                    status="error",
                    action="missing_channel",
                    error="configured channel could not be resolved",
                )
            )
            continue

        try:
            if record is None:
                message_id = await send(target, event)
                action = "sent"
            else:
                message_id = await edit(target, record.message_id, event)
                action = "cancelled" if event.is_cancelled else "edited"
        except Exception as exc:
            logger.warning(
                "일본 EEW 알림 처리 실패: guild=%s channel=%s event=%s serial=%s",
                guild_id,
                channel_id,
                event.event_id,
                event.serial,
                exc_info=True,
            )
            results.append(
                _error_result(
                    guild_id,
                    channel_id,
                    event,
                    "send_failed" if record is None else "edit_failed",
                    exc,
                )
            )
            continue

        if message_id is None:
            message_id = record.message_id if record is not None else None
        if message_id is None:
            results.append(
                EarthquakeAlertResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    event_id=event.event_id,
                    serial=event.serial,
                    status="error",
                    action="missing_message_id",
                    error="Discord message ID was not returned",
                )
            )
            continue

        updated_state = remember_jma_eew_message(
            state,
            event_id=event.event_id,
            serial=event.serial,
            message_id=message_id,
        )
        try:
            await save(guild_id, updated_state)
        except Exception as exc:
            logger.warning(
                "일본 EEW 상태 저장 실패: guild=%s event=%s serial=%s",
                guild_id,
                event.event_id,
                event.serial,
                exc_info=True,
            )
            results.append(
                _error_result(
                    guild_id,
                    channel_id,
                    event,
                    "state_save_failed",
                    exc,
                    message_id=message_id,
                )
            )
            continue

        results.append(
            EarthquakeAlertResult(
                guild_id=guild_id,
                channel_id=channel_id,
                event_id=event.event_id,
                serial=event.serial,
                message_id=message_id,
                action=action,
            )
        )

    return results


async def resolve_earthquake_alert_channel(
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


async def send_jma_eew_alert(
    target: object,
    event: JmaEewEvent,
) -> int | None:
    message = await target.send(
        embed=build_jma_eew_embed(event),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return getattr(message, "id", None)


async def edit_jma_eew_alert(
    target: object,
    message_id: int,
    event: JmaEewEvent,
) -> int | None:
    try:
        message = await target.fetch_message(int(message_id))
    except discord.NotFound:
        return await send_jma_eew_alert(target, event)
    await message.edit(
        embed=build_jma_eew_embed(event),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return getattr(message, "id", int(message_id))


def build_jma_eew_embed(event: JmaEewEvent) -> discord.Embed:
    if event.is_cancelled:
        report_type = "취소"
    elif event.is_warning:
        report_type = "경보"
    else:
        report_type = "예보"

    embed = discord.Embed(
        title=f"JMA 긴급지진속보 {report_type} | {_magnitude_text(event)}",
        description=f"**{event.hypocenter}**",
        color=_jma_eew_color(event),
        timestamp=event.announced_at,
    )
    embed.add_field(
        name="규모",
        value=f"**{_magnitude_text(event)}**",
        inline=True,
    )
    embed.add_field(
        name="깊이",
        value=(
            f"{event.depth_km:g} km"
            if event.depth_km is not None
            else "미상"
        ),
        inline=True,
    )
    embed.add_field(
        name="최대 예상 진도",
        value=event.max_intensity or "미상",
        inline=True,
    )
    embed.add_field(
        name="발표 단계",
        value=f"제 {event.serial}보" + ("\n최종보" if event.is_final else ""),
        inline=True,
    )
    embed.add_field(
        name="발표 시각",
        value=_discord_time(event.announced_at),
        inline=True,
    )
    embed.add_field(
        name="발생 추정",
        value=(
            _discord_time(event.origin_at)
            if event.origin_at is not None
            else "미상"
        ),
        inline=True,
    )
    if event.latitude is not None and event.longitude is not None:
        coordinates_url = (
            "https://www.google.com/maps/search/?api=1&query="
            f"{event.latitude:.4f},{event.longitude:.4f}"
        )
        embed.add_field(
            name="추정 진원",
            value=(
                f"[{event.latitude:.4f}, {event.longitude:.4f}]"
                f"({coordinates_url})"
            ),
            inline=False,
        )
    if event.warn_areas:
        embed.add_field(
            name="예상 지역",
            value=_warn_area_text(event),
            inline=False,
        )
    if event.is_cancelled:
        embed.add_field(
            name="상태",
            value="기상청에서 이 긴급지진속보를 취소했습니다.",
            inline=False,
        )
    elif event.is_assumption:
        embed.add_field(
            name="분석 상태",
            value="PLUM법 추정 진원 정보입니다.",
            inline=False,
        )
    embed.set_footer(
        text=(
            "정보 출처: 일본 기상청 JMA | 중계: Wolfx 비공식 API | "
            "속보 수치는 후속 보에서 변경되거나 취소될 수 있습니다."
        )
    )
    return embed


async def _get_earthquake_alert_channels() -> dict[int, int]:
    from util.guild.channel_settings import get_channels_by_purpose

    return await get_channels_by_purpose(EARTHQUAKE_ALERT_CHANNEL_TYPE)


def _magnitude_text(event: JmaEewEvent) -> str:
    return f"M{event.magnitude:.1f}" if event.magnitude is not None else "M 미상"


def _discord_time(value: object) -> str:
    timestamp = int(value.timestamp())
    return f"<t:{timestamp}:f>\n<t:{timestamp}:R>"


def _warn_area_text(event: JmaEewEvent) -> str:
    lines = []
    for area in event.warn_areas[:10]:
        intensity = area.maximum_intensity or area.minimum_intensity or "미상"
        arrival = f" | {area.arrival_status}" if area.arrival_status else ""
        lines.append(f"{area.name}: 진도 {intensity}{arrival}")
    if len(event.warn_areas) > 10:
        lines.append(f"외 {len(event.warn_areas) - 10}개 지역")
    return "\n".join(lines)


def _jma_eew_color(event: JmaEewEvent) -> discord.Color:
    if event.is_cancelled:
        return discord.Color.light_grey()
    if event.magnitude is not None and event.magnitude >= 6.0:
        return discord.Color.red()
    if event.magnitude is not None and event.magnitude >= 5.0:
        return discord.Color.orange()
    if event.magnitude is not None and event.magnitude >= 4.0:
        return discord.Color.yellow()
    if event.magnitude is not None and event.magnitude >= 3.0:
        return discord.Color.green()
    return discord.Color.light_grey()


def _skipped_result(
    guild_id: int,
    channel_id: int,
    event: JmaEewEvent,
    action: str,
) -> EarthquakeAlertResult:
    return EarthquakeAlertResult(
        guild_id=guild_id,
        channel_id=channel_id,
        event_id=event.event_id,
        serial=event.serial,
        status="skipped",
        action=action,
    )


def _error_result(
    guild_id: int,
    channel_id: int,
    event: JmaEewEvent,
    action: str,
    error: Exception,
    *,
    message_id: int | None = None,
) -> EarthquakeAlertResult:
    return EarthquakeAlertResult(
        guild_id=guild_id,
        channel_id=channel_id,
        event_id=event.event_id,
        serial=event.serial,
        message_id=message_id,
        status="error",
        action=action,
        error=str(error),
    )
