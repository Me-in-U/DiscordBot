from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import discord

from util.earthquake.alerts import (
    EarthquakeAlertResult,
    get_earthquake_alert_channels,
    resolve_earthquake_alert_channel,
)
from util.earthquake.emsc import (
    EMSC_CREATE_ACTIONS,
    EMSC_KOREA_EVERYONE_MAGNITUDE,
    EmscEvent,
    is_earthquake_emsc_event,
    is_japan_emsc_event,
    is_korea_emsc_event,
    minimum_magnitude_for_emsc_event,
)
from util.earthquake.map_image import (
    EARTHQUAKE_MAP_FILENAME,
    build_earthquake_map_file,
    build_openstreetmap_url,
)
from util.earthquake.state import (
    EmscAlertState,
    find_emsc_record,
    load_emsc_alert_state,
    remember_emsc_message,
    reset_emsc_alert_state,
    save_emsc_alert_state,
)


logger = logging.getLogger(__name__)

GetChannels = Callable[[], Awaitable[dict[int, int]]]
LoadState = Callable[[int], Awaitable[EmscAlertState]]
SaveState = Callable[[int, EmscAlertState], Awaitable[None]]
ResolveChannel = Callable[[object, int], Awaitable[object | None]]
SendAlert = Callable[[object, EmscEvent, bool], Awaitable[int | None]]
EditAlert = Callable[[object, int, EmscEvent, bool], Awaitable[int | None]]


async def process_emsc_event(
    bot: object,
    event: EmscEvent,
    *,
    get_channels: GetChannels | None = None,
    load_state: LoadState | None = None,
    save_state: SaveState | None = None,
    resolve_channel: ResolveChannel | None = None,
    send_alert: SendAlert | None = None,
    edit_alert: EditAlert | None = None,
) -> list[EarthquakeAlertResult]:
    get_configured_channels = get_channels or get_earthquake_alert_channels
    channels = await get_configured_channels()
    if not channels:
        return []
    if not is_earthquake_emsc_event(event):
        return _skip_all(channels, event, "non_earthquake")
    if is_japan_emsc_event(event):
        return _skip_all(channels, event, "japan_duplicate")
    minimum_magnitude = minimum_magnitude_for_emsc_event(event)
    if (
        event.action in EMSC_CREATE_ACTIONS
        and not event.is_at_least_magnitude(minimum_magnitude)
    ):
        return _skip_all(channels, event, "below_threshold")

    load = load_state or load_emsc_alert_state
    save = save_state or save_emsc_alert_state
    resolve = resolve_channel or resolve_earthquake_alert_channel
    send = send_alert or send_emsc_alert
    edit = edit_alert or edit_emsc_alert
    results: list[EarthquakeAlertResult] = []

    for guild_id, channel_id in channels.items():
        try:
            state = await load(guild_id)
        except Exception as exc:
            logger.warning(
                "EMSC 지진 상태 조회 실패: guild=%s",
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
            state = reset_emsc_alert_state(channel_id)

        record = find_emsc_record(state, event.event_id)
        if record is not None and record.revision >= event.revision:
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
            if event.is_deleted:
                results.append(
                    _skipped_result(
                        guild_id,
                        channel_id,
                        event,
                        "untracked_delete",
                    )
                )
                continue
            if not event.is_at_least_magnitude(minimum_magnitude):
                results.append(
                    _skipped_result(
                        guild_id,
                        channel_id,
                        event,
                        "below_threshold",
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
                    status="error",
                    action="missing_channel",
                    error="configured channel could not be resolved",
                )
            )
            continue

        notify_everyone = _should_show_everyone(event) and not (
            record is not None and record.everyone_notified
        )
        try:
            if record is None:
                message_id = await send(target, event, notify_everyone)
                action = "sent"
            else:
                message_id = await edit(
                    target,
                    record.message_id,
                    event,
                    notify_everyone,
                )
                action = "cancelled" if event.is_deleted else "edited"
        except Exception as exc:
            logger.warning(
                "EMSC 지진 알림 처리 실패: guild=%s channel=%s event=%s",
                guild_id,
                channel_id,
                event.event_id,
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
                    status="error",
                    action="missing_message_id",
                    error="Discord message ID was not returned",
                )
            )
            continue

        updated_state = remember_emsc_message(
            state,
            event_id=event.event_id,
            revision=event.revision,
            message_id=message_id,
            everyone_notified=(
                (record.everyone_notified if record is not None else False)
                or notify_everyone
            ),
        )
        try:
            await save(guild_id, updated_state)
        except Exception as exc:
            logger.warning(
                "EMSC 지진 상태 저장 실패: guild=%s event=%s",
                guild_id,
                event.event_id,
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
                message_id=message_id,
                action=action,
            )
        )

    return results


async def send_emsc_alert(
    target: object,
    event: EmscEvent,
    notify_everyone: bool | None = None,
) -> int | None:
    map_file = await build_earthquake_map_file(event)
    show_everyone = _should_show_everyone(event)
    should_notify = (
        show_everyone
        if notify_everyone is None
        else show_everyone and bool(notify_everyone)
    )
    send_options = {
        "embed": build_emsc_embed(
            event,
            include_map=map_file is not None,
        ),
        "allowed_mentions": _allowed_mentions(should_notify),
    }
    if show_everyone:
        send_options["content"] = "@everyone"
    if map_file is not None:
        send_options["file"] = map_file
    message = await target.send(**send_options)
    return getattr(message, "id", None)


async def edit_emsc_alert(
    target: object,
    message_id: int,
    event: EmscEvent,
    notify_everyone: bool = False,
) -> int | None:
    try:
        message = await target.fetch_message(int(message_id))
    except discord.NotFound:
        return await send_emsc_alert(
            target,
            event,
            notify_everyone=notify_everyone,
        )

    if notify_everyone and _should_show_everyone(event):
        replacement_message_id = await send_emsc_alert(
            target,
            event,
            notify_everyone=True,
        )
        try:
            await message.delete()
        except discord.DiscordException:
            logger.warning(
                "한국 M5.5 이상 EMSC 기존 메시지 삭제 실패: message=%s",
                message_id,
                exc_info=True,
            )
        return replacement_message_id

    map_file = await build_earthquake_map_file(event)
    existing_map = next(
        (
            attachment
            for attachment in getattr(message, "attachments", ())
            if getattr(attachment, "filename", None)
            == EARTHQUAKE_MAP_FILENAME
        ),
        None,
    )
    edit_options = {
        "content": "@everyone" if _should_show_everyone(event) else None,
        "embed": build_emsc_embed(
            event,
            include_map=map_file is not None or existing_map is not None,
        ),
        "allowed_mentions": discord.AllowedMentions.none(),
    }
    if map_file is not None:
        edit_options["attachments"] = [map_file]
    elif existing_map is not None:
        edit_options["attachments"] = [existing_map]
    await message.edit(**edit_options)
    return getattr(message, "id", int(message_id))


def build_emsc_embed(
    event: EmscEvent,
    *,
    include_map: bool = False,
) -> discord.Embed:
    report_type = _report_type(event)
    embed = discord.Embed(
        title=f"EMSC 지진정보 {report_type} | {_magnitude_text(event)}",
        description=f"**{event.region or '지역 정보 없음'}**",
        color=_emsc_color(event),
        timestamp=event.updated_at,
    )
    magnitude_value = f"**{_magnitude_text(event)}**"
    if event.magnitude_type:
        magnitude_value += f"\n{event.magnitude_type.upper()}"
    embed.add_field(name="규모", value=magnitude_value, inline=True)
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
        value="제공 안 함",
        inline=True,
    )
    embed.add_field(
        name="발표 단계",
        value=report_type,
        inline=True,
    )
    embed.add_field(
        name="발표 시각",
        value=_discord_time(event.updated_at),
        inline=True,
    )
    embed.add_field(
        name="발생 추정",
        value=_discord_time(event.occurred_at),
        inline=True,
    )
    if event.latitude is not None and event.longitude is not None:
        coordinates_url = build_openstreetmap_url(event)
        embed.add_field(
            name="추정 진원",
            value=f"[지도에서 크게 보기]({coordinates_url})",
            inline=False,
        )
        if include_map:
            embed.set_image(url=f"attachment://{EARTHQUAKE_MAP_FILENAME}")
    if event.is_deleted:
        embed.add_field(
            name="상태",
            value="EMSC에서 이 지진 정보를 삭제했습니다.",
            inline=False,
        )
    authority = event.authority or "EMSC"
    embed.set_footer(
        text=(
            f"정보 출처: EMSC/CSEM | 원자료 기관: {authority} | "
            "https://www.emsc-csem.org | 근실시간 예비 정보로 "
            "수치가 수정되거나 삭제될 수 있습니다."
        )
    )
    return embed


def _should_show_everyone(event: EmscEvent) -> bool:
    return (
        not event.is_deleted
        and is_korea_emsc_event(event)
        and event.magnitude is not None
        and event.magnitude >= EMSC_KOREA_EVERYONE_MAGNITUDE
    )


def _allowed_mentions(notify_everyone: bool) -> discord.AllowedMentions:
    if not notify_everyone:
        return discord.AllowedMentions.none()
    return discord.AllowedMentions(
        everyone=True,
        users=False,
        roles=False,
        replied_user=False,
    )


def _report_type(event: EmscEvent) -> str:
    if event.is_deleted:
        return "삭제"
    if event.action in EMSC_CREATE_ACTIONS:
        return "신규"
    return "수정"


def _magnitude_text(event: EmscEvent) -> str:
    return f"M{event.magnitude:.1f}" if event.magnitude is not None else "M 미상"


def _discord_time(value: object) -> str:
    timestamp = int(value.timestamp())
    return f"<t:{timestamp}:f>\n<t:{timestamp}:R>"


def _emsc_color(event: EmscEvent) -> discord.Color:
    if event.is_deleted:
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


def _skip_all(
    channels: dict[int, int],
    event: EmscEvent,
    action: str,
) -> list[EarthquakeAlertResult]:
    return [
        _skipped_result(guild_id, channel_id, event, action)
        for guild_id, channel_id in channels.items()
    ]


def _skipped_result(
    guild_id: int,
    channel_id: int,
    event: EmscEvent,
    action: str,
) -> EarthquakeAlertResult:
    return EarthquakeAlertResult(
        guild_id=guild_id,
        channel_id=channel_id,
        event_id=event.event_id,
        status="skipped",
        action=action,
    )


def _error_result(
    guild_id: int,
    channel_id: int,
    event: EmscEvent,
    action: str,
    error: Exception,
    *,
    message_id: int | None = None,
) -> EarthquakeAlertResult:
    return EarthquakeAlertResult(
        guild_id=guild_id,
        channel_id=channel_id,
        event_id=event.event_id,
        message_id=message_id,
        status="error",
        action=action,
        error=str(error),
    )
