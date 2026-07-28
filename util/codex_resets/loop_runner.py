from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from util.codex_resets.events import refresh_codex_reset_notifications


class CodexResetLoopResult(Protocol):
    guild_id: int
    channel_id: int | None
    tweet_id: str | None
    action: str | None
    status: str
    error: str | None


RefreshCodexResetNotifications = Callable[
    [object],
    Awaitable[Sequence[CodexResetLoopResult]],
]
LogMessage = Callable[[str], None]


async def run_codex_reset_notification_loop(
    bot: object,
    *,
    refresh_notifications: RefreshCodexResetNotifications = (
        refresh_codex_reset_notifications
    ),
    log: LogMessage = print,
) -> int:
    results = await refresh_notifications(bot)
    sent_count = 0
    for result in results:
        if result.status == "ok" and result.action == "sent":
            sent_count += 1
            continue
        if result.status == "skipped":
            continue
        log(
            f"Codex 리셋 알림 실패: guild={result.guild_id} "
            f"channel={result.channel_id} tweet={result.tweet_id} "
            f"action={result.action} error={result.error}"
        )

    if sent_count:
        log(f"Codex 리셋 알림 {sent_count}건 전송 완료")
    return sent_count
