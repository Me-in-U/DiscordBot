from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from func.find1557 import clearCount
from util.db import fetch_all


logger = logging.getLogger(__name__)

CountRow = Mapping[str, Any]
FetchCounts = Callable[[], Sequence[CountRow] | Awaitable[Sequence[CountRow]]]
ClearCounts = Callable[[], None | Awaitable[None]]
LogMessage = Callable[[str], None]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def fetch_weekly_1557_counts() -> list[CountRow]:
    return await fetch_all("SELECT user_id, count FROM counter_1557")


async def run_weekly_1557_report(
    bot,
    *,
    target_channel_id: int,
    now: datetime,
    fetch_counts: FetchCounts = fetch_weekly_1557_counts,
    clear_counts: ClearCounts = clearCount,
    log: LogMessage = print,
) -> bool:
    if now.weekday() != 0:
        return False

    log(f"Debug {['월','화','수','목','금','토','일'][now.weekday()]}요일")
    target_channel = bot.get_channel(target_channel_id)
    if not target_channel:
        log("대상 채널을 찾을 수 없습니다.")
        return False

    try:
        rows = await _maybe_await(fetch_counts())
        data = {row["user_id"]: row["count"] for row in rows}
    except Exception:
        logger.exception("1557Counter DB 로드 중 오류 발생")
        data = {}

    if not data:
        report = "📊 이번 주 1557 카운트 기록된 사용자가 없습니다."
    else:
        sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
        lines = [f"<@{user_id}>: {count}번" for user_id, count in sorted_items]
        report = "# 📊 주간 1557 카운트 보고\n" + "\n".join(lines)

    await target_channel.send(report)
    log(f"[{now}] 주간 1557 카운트 보고 완료.")
    await _maybe_await(clear_counts())
    return True
