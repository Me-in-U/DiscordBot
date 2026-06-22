from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import discord

from util.db import execute_query, fetch_all, fetch_one

MAX_DDAY_TITLE_LENGTH = 100
SEOUL_TZ = timezone(timedelta(hours=9))


@dataclass(frozen=True, slots=True)
class DdayEvent:
    id: int
    guild_id: int
    title: str
    target_date: date
    show_after: bool
    created_by: int
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class DdayUpdateResult:
    guild_id: int
    channel_id: int | None = None
    message_id: int | None = None
    action: str | None = None
    status: str = "ok"
    error: str | None = None


def parse_dday_date(value: str) -> date:
    text = str(value or "").strip()
    for date_format in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    raise ValueError(
        "날짜는 YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, YYYYMMDD 형식으로 입력해 주세요."
    )


def validate_dday_title(value: str) -> str:
    title = str(value or "").strip()
    if not title:
        raise ValueError("제목을 입력해 주세요.")
    if len(title) > MAX_DDAY_TITLE_LENGTH:
        raise ValueError(f"제목은 {MAX_DDAY_TITLE_LENGTH}자 이하로 입력해 주세요.")
    return title


def calculate_dday_label(target_date: date, today: date | None = None) -> str:
    current_date = today or _today()
    delta_days = (target_date - current_date).days
    if delta_days == 0:
        return "D-Day"
    if delta_days > 0:
        return f"D-{delta_days}"
    return f"D+{abs(delta_days)}"


def filter_visible_dday_events(
    events: list[DdayEvent],
    today: date | None = None,
) -> list[DdayEvent]:
    current_date = today or _today()
    visible = [
        event
        for event in events
        if event.target_date >= current_date or event.show_after
    ]
    return sorted(visible, key=lambda event: _event_sort_key(event, current_date))


def build_dday_list_embed(
    events: list[DdayEvent],
    *,
    today: date | None = None,
) -> discord.Embed:
    current_date = today or _today()
    embed = discord.Embed(title="📅 DDAY 목록", color=discord.Color.blurple())
    if not events:
        embed.description = "등록된 DDAY가 없습니다."
        return embed

    groups = _group_events(events, current_date, include_excluded=True)
    for field_name, field_events in groups:
        if not field_events:
            continue
        embed.add_field(
            name=field_name,
            value=_format_event_lines(field_events, current_date),
            inline=False,
        )

    embed.set_footer(text=f"총 {len(events)}개")
    return embed


def build_dday_announcement_embed(
    events: list[DdayEvent],
    *,
    today: date | None = None,
) -> discord.Embed | None:
    current_date = today or _today()
    visible_events = filter_visible_dday_events(events, current_date)
    if not visible_events:
        return None

    embed = discord.Embed(
        title="📅 오늘의 DDAY",
        description="DDAY를 알려드립니다.",
        color=discord.Color.gold(),
    )
    for field_name, field_events in _group_events(
        visible_events,
        current_date,
        include_excluded=False,
    ):
        if not field_events:
            continue
        embed.add_field(
            name=field_name,
            value=_format_event_lines(field_events, current_date),
            inline=False,
        )
    return embed


async def list_dday_events(guild_id: int) -> list[DdayEvent]:
    query = """
        SELECT *
        FROM dday_events
        WHERE guild_id = %s
        ORDER BY target_date ASC, title ASC, id ASC
    """
    rows = await fetch_all(query, (int(guild_id),))
    return [row_to_dday_event(row) for row in rows]


async def get_dday_event(event_id: int) -> DdayEvent | None:
    row = await fetch_one("SELECT * FROM dday_events WHERE id = %s", (int(event_id),))
    return row_to_dday_event(row) if row else None


async def create_dday_event(
    *,
    guild_id: int,
    title: str,
    target_date: date,
    show_after: bool,
    created_by: int,
) -> int:
    query = """
        INSERT INTO dday_events (
            guild_id,
            title,
            target_date,
            show_after,
            created_by
        )
        VALUES (%s, %s, %s, %s, %s)
    """
    return int(
        await execute_query(
            query,
            (
                int(guild_id),
                validate_dday_title(title),
                target_date,
                bool(show_after),
                int(created_by),
            ),
        )
    )


async def delete_dday_event(guild_id: int, event_id: int) -> DdayEvent | None:
    event = await get_dday_event(event_id)
    if event is None or event.guild_id != int(guild_id):
        return None

    await execute_query(
        "DELETE FROM dday_events WHERE id = %s AND guild_id = %s",
        (int(event_id), int(guild_id)),
    )
    return event


async def refresh_dday_messages(
    bot: discord.Client,
    guild_id: int | None = None,
) -> list[DdayUpdateResult]:
    from util.celebration.announcements import get_celebration_channels

    channels = await get_celebration_channels(bot, guild_id)
    current_date = _today()
    results: list[DdayUpdateResult] = []

    for current_guild_id, channel in channels.items():
        try:
            events = await list_dday_events(current_guild_id)
            embed = build_dday_announcement_embed(events, today=current_date)
            if embed is None:
                results.append(
                    DdayUpdateResult(
                        guild_id=current_guild_id,
                        channel_id=channel.id,
                        action="no_events",
                        status="skipped",
                    )
                )
                continue

            sent_message = await channel.send(embed=embed)
            results.append(
                DdayUpdateResult(
                    guild_id=current_guild_id,
                    channel_id=channel.id,
                    message_id=sent_message.id,
                    action="sent",
                )
            )
        except Exception as exc:
            results.append(
                DdayUpdateResult(
                    guild_id=current_guild_id,
                    channel_id=channel.id,
                    status="error",
                    error=str(exc),
                )
            )

    return results


def row_to_dday_event(row: dict[str, Any]) -> DdayEvent:
    return DdayEvent(
        id=int(row["id"]),
        guild_id=int(row["guild_id"]),
        title=str(row["title"]),
        target_date=_coerce_date(row["target_date"]),
        show_after=_optional_bool(row.get("show_after"), default=False),
        created_by=int(row["created_by"]),
        created_at=_optional_datetime_text(row.get("created_at")),
        updated_at=_optional_datetime_text(row.get("updated_at")),
    )


def _today() -> date:
    return datetime.now(SEOUL_TZ).date()


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_dday_date(str(value))


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _optional_datetime_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _event_sort_key(event: DdayEvent, today: date) -> tuple[int, date, str, int]:
    if event.target_date == today:
        group = 0
    elif event.target_date > today:
        group = 1
    else:
        group = 2
    return (group, event.target_date, event.title, event.id)


def _group_events(
    events: list[DdayEvent],
    today: date,
    *,
    include_excluded: bool,
) -> list[tuple[str, list[DdayEvent]]]:
    sorted_events = sorted(events, key=lambda event: _event_sort_key(event, today))
    today_events = [event for event in sorted_events if event.target_date == today]
    future_events = [event for event in sorted_events if event.target_date > today]
    past_events = [
        event
        for event in sorted_events
        if event.target_date < today and event.show_after
    ]
    groups = [
        ("오늘 D-0", today_events),
        ("다가오는 D-DAY", future_events),
        ("지난 D+DAY", past_events),
    ]
    if include_excluded:
        excluded_events = [
            event
            for event in sorted_events
            if event.target_date < today and not event.show_after
        ]
        groups.append(("자동 공지 제외", excluded_events))
    return groups


def _format_event_lines(events: list[DdayEvent], today: date) -> str:
    lines = [
        (
            f"**{event.title}** · `{calculate_dday_label(event.target_date, today)}`"
            f" · {event.target_date.isoformat()}"
        )
        for event in events
    ]
    return _truncate_field_value(lines)


def _truncate_field_value(lines: list[str]) -> str:
    value = "\n".join(lines)
    if len(value) <= 1024:
        return value

    kept: list[str] = []
    for line in lines:
        candidate = "\n".join(kept + [line, "…"])
        if len(candidate) > 1024:
            break
        kept.append(line)
    kept.append("…")
    return "\n".join(kept)
