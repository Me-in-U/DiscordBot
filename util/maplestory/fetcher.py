from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import aiohttp

from util.maplestory.parser import (
    MAPLESTORY_NOTICE_LIST_URL,
    MAPLESTORY_ONGOING_EVENT_LIST_URL,
    MapleStoryEvent,
    MapleStoryNotice,
    parse_maplestory_event_detail,
    parse_maplestory_notice_detail,
    parse_maplestory_notice_list,
    parse_maplestory_ongoing_event_url,
)


logger = logging.getLogger(__name__)

MAPLESTORY_IGNORED_NOTICE_TITLE_MARKERS = (
    "신고보상안내",
    "우수테스터발표안내",
    "npay",
    "네이버페이",
)

MAPLESTORY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/132.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

FetchHtml = Callable[[str], Awaitable[str]]


async def fetch_sunday_maple_event(
    fetch_html: FetchHtml | None = None,
) -> MapleStoryEvent | None:
    fetch = fetch_html or _fetch_html
    list_html = await fetch(MAPLESTORY_ONGOING_EVENT_LIST_URL)
    event_url = await asyncio.to_thread(parse_maplestory_ongoing_event_url, list_html)
    if not event_url:
        return None

    detail_html = await fetch(event_url)
    return await asyncio.to_thread(
        parse_maplestory_event_detail,
        detail_html,
        event_url=event_url,
    )


async def fetch_latest_maplestory_notices(
    fetch_html: FetchHtml | None = None,
    *,
    limit: int = 10,
) -> list[MapleStoryNotice]:
    fetch = fetch_html or _fetch_html
    list_html = await fetch(MAPLESTORY_NOTICE_LIST_URL)
    notices = await asyncio.to_thread(parse_maplestory_notice_list, list_html)
    notices = [
        notice
        for notice in notices
        if not _should_ignore_maplestory_notice_alert(notice)
    ]
    hydrated: list[MapleStoryNotice] = []
    for notice in notices[:limit]:
        try:
            detail_html = await fetch(notice.url)
            hydrated.append(
                await asyncio.to_thread(
                    parse_maplestory_notice_detail,
                    detail_html,
                    notice,
                )
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            logger.warning(
                "메이플스토리 공지 상세 조회 실패: notice=%s",
                notice.notice_id,
                exc_info=True,
            )
            hydrated.append(notice)
    return hydrated


def _should_ignore_maplestory_notice_alert(notice: MapleStoryNotice) -> bool:
    compact_title = "".join((notice.title or "").split()).lower()
    return any(
        marker in compact_title
        for marker in MAPLESTORY_IGNORED_NOTICE_TITLE_MARKERS
    )


async def _fetch_html(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(
        headers=MAPLESTORY_HEADERS,
        timeout=timeout,
        trust_env=False,
    ) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.text()
