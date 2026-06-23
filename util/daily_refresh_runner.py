from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from util.celebration import refresh_celebration_messages
from util.dday import refresh_dday_messages
from util.maplestory_events import refresh_sunday_maple_messages


class RefreshResult(Protocol):
    status: str
    guild_id: int | None
    channel_id: int | None
    error: str | None


RefreshFunc = Callable[[Any], Awaitable[Iterable[RefreshResult]]]
ReloadRecentMessages = Callable[[], Awaitable[None]]
LogFunc = Callable[[str], None]


@dataclass(frozen=True)
class DailyRefreshSummary:
    celebration_success_count: int = 0
    dday_success_count: int = 0
    sunday_maple_success_count: int = 0


def _count_successes_and_log_failures(
    results: Iterable[RefreshResult],
    *,
    failure_label: str,
    log: LogFunc,
    skip_statuses: set[str] | None = None,
) -> int:
    skip_statuses = skip_statuses or set()
    success_count = 0

    for result in results:
        if result.status == "ok":
            success_count += 1
            continue
        if result.status in skip_statuses:
            continue
        log(
            f"{failure_label}: guild={result.guild_id} "
            f"channel={result.channel_id} error={result.error}"
        )

    return success_count


async def run_daily_refreshes(
    bot: Any,
    *,
    now: datetime,
    reload_recent_messages: ReloadRecentMessages,
    refresh_celebration: RefreshFunc = refresh_celebration_messages,
    refresh_dday: RefreshFunc = refresh_dday_messages,
    refresh_sunday_maple: RefreshFunc = refresh_sunday_maple_messages,
    log: LogFunc = print,
) -> DailyRefreshSummary:
    celebration_results = await refresh_celebration(bot)
    celebration_success_count = _count_successes_and_log_failures(
        celebration_results,
        failure_label="기념일 공지 갱신 실패",
        log=log,
    )
    if celebration_success_count:
        log(f"[{now}] 기념일 공지 {celebration_success_count}개 채널 갱신 완료.")

    dday_results = await refresh_dday(bot)
    dday_success_count = _count_successes_and_log_failures(
        dday_results,
        failure_label="DDAY 공지 갱신 실패",
        log=log,
        skip_statuses={"skipped"},
    )
    if dday_success_count:
        log(f"[{now}] DDAY 공지 {dday_success_count}개 채널 전송 완료.")

    sunday_maple_success_count = 0
    if now.weekday() == 6:
        sunday_maple_results = await refresh_sunday_maple(bot)
        sunday_maple_success_count = _count_successes_and_log_failures(
            sunday_maple_results,
            failure_label="썬데이메이플 공지 전송 실패",
            log=log,
            skip_statuses={"skipped"},
        )
        if sunday_maple_success_count:
            log(f"[{now}] 썬데이메이플 공지 {sunday_maple_success_count}개 채널 전송 완료.")

    bot.USER_MESSAGES = {}
    await reload_recent_messages()
    log(f"[{now}] user_messages 초기화 완료.")

    return DailyRefreshSummary(
        celebration_success_count=celebration_success_count,
        dday_success_count=dday_success_count,
        sunday_maple_success_count=sunday_maple_success_count,
    )
