from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from util.maplestory_events import refresh_maplestory_notice_messages


class MapleStoryNoticeLoopResult(Protocol):
    guild_id: int
    channel_id: int | None
    notice_id: str | None
    action: str | None
    status: str
    error: str | None


RefreshMapleStoryNotices = Callable[
    [object],
    Awaitable[Sequence[MapleStoryNoticeLoopResult]],
]
LogMessage = Callable[[str], None]


async def run_maplestory_notice_loop(
    bot: object,
    *,
    refresh_notices: RefreshMapleStoryNotices = refresh_maplestory_notice_messages,
    log: LogMessage = print,
) -> int:
    results = await refresh_notices(bot)
    sent_count = 0
    for result in results:
        if result.status == "ok" and result.action == "sent":
            sent_count += 1
            continue
        if result.status == "skipped":
            continue
        log(
            f"메이플스토리 공지 알림 실패: guild={result.guild_id} "
            f"channel={result.channel_id} notice={result.notice_id} "
            f"action={result.action} error={result.error}"
        )

    if sent_count:
        log(f"메이플스토리 공지 알림 {sent_count}건 전송 완료")
    return sent_count
