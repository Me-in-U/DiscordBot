from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import aiohttp
import discord


logger = logging.getLogger(__name__)


MAPLESTORY_BASE_URL = "https://maplestory.nexon.com"
MAPLESTORY_ONGOING_EVENT_LIST_URL = f"{MAPLESTORY_BASE_URL}/News/Event/Ongoing"
MAPLESTORY_NOTICE_LIST_URL = f"{MAPLESTORY_BASE_URL}/News/Notice"
MAPLESTORY_NOTICE_CHANNEL_TYPE = "maplestory_notice"
MAPLESTORY_NOTICE_STATE_KEY = "maplestoryNoticeState"
MAPLESTORY_NOTICE_FETCH_LIMIT = 10
MAPLESTORY_NOTICE_STATE_LIMIT = 50
SUNDAY_MAPLE_EVENT_TITLE = "스페셜 썬데이 메이플"
MAPLESTORY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/132.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

FetchHtml = Callable[[str], Awaitable[str]]
FetchEvent = Callable[[], Awaitable["MapleStoryEvent | None"]]
FetchNotices = Callable[[], Awaitable[list["MapleStoryNotice"]]]


@dataclass(frozen=True, slots=True)
class MapleStoryEvent:
    title: str
    url: str
    period: str = ""
    image_urls: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MapleStoryNotice:
    notice_id: str
    category: str
    title: str
    url: str
    summary: str = ""


@dataclass(slots=True)
class SundayMapleUpdateResult:
    guild_id: int
    channel_id: int | None = None
    message_id: int | None = None
    action: str | None = None
    status: str = "ok"
    error: str | None = None


@dataclass(slots=True)
class MapleStoryNoticeUpdateResult:
    guild_id: int
    channel_id: int | None = None
    notice_id: str | None = None
    action: str | None = None
    status: str = "ok"
    error: str | None = None


def parse_maplestory_ongoing_event_url(
    html: str,
    target_title: str = SUNDAY_MAPLE_EVENT_TITLE,
) -> str | None:
    parser = _MapleStoryOngoingEventParser(target_title)
    parser.feed(html)
    return parser.event_url


def parse_maplestory_notice_list(html: str) -> list[MapleStoryNotice]:
    parser = _MapleStoryNoticeListParser()
    parser.feed(html)
    return parser.notices


def parse_maplestory_event_detail(html: str, event_url: str) -> MapleStoryEvent:
    parser = _MapleStoryEventDetailParser(event_url)
    parser.feed(html)
    return MapleStoryEvent(
        title=parser.title or SUNDAY_MAPLE_EVENT_TITLE,
        url=event_url,
        period=parser.period,
        image_urls=parser.image_urls,
    )


def parse_maplestory_notice_detail(
    html: str,
    notice: MapleStoryNotice,
) -> MapleStoryNotice:
    parser = _MapleStoryNoticeDetailParser()
    parser.feed(html)
    return MapleStoryNotice(
        notice_id=notice.notice_id,
        category=parser.category or notice.category,
        title=parser.title or notice.title,
        url=notice.url,
        summary=_build_notice_summary(parser.body_text),
    )


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
    limit: int = MAPLESTORY_NOTICE_FETCH_LIMIT,
) -> list[MapleStoryNotice]:
    fetch = fetch_html or _fetch_html
    list_html = await fetch(MAPLESTORY_NOTICE_LIST_URL)
    notices = await asyncio.to_thread(parse_maplestory_notice_list, list_html)
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


def build_sunday_maple_event_embeds(event: MapleStoryEvent) -> list[discord.Embed]:
    embeds: list[discord.Embed] = []
    for index, image_url in enumerate(event.image_urls[:10], start=1):
        embed = discord.Embed(
            title=event.title if index == 1 else f"{event.title} ({index})",
            url=event.url,
            description=event.period or None,
            color=discord.Color.green(),
        )
        embed.set_image(url=image_url)
        embed.set_footer(text="출처: 메이플스토리 공식 이벤트")
        embeds.append(embed)
    return embeds


def build_maplestory_notice_message(notice: MapleStoryNotice) -> str:
    lines = ["# 공지", "", notice.title]
    if notice.summary:
        lines.append(_truncate_discord_text(notice.summary, 700))
    lines.extend(["", f"[바로가기]({notice.url})"])
    return "\n".join(lines)


def build_maplestory_notice_fingerprint(notice: MapleStoryNotice) -> str:
    payload = "\n".join(
        [
            notice.notice_id,
            notice.category,
            notice.title,
            notice.summary,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def maplestory_notice_state_from_notices(
    notices: list[MapleStoryNotice],
    *,
    limit: int = MAPLESTORY_NOTICE_STATE_LIMIT,
) -> dict[str, Any]:
    state: dict[str, Any] = {"notices": {}, "recentNoticeIds": []}
    for notice in notices[:limit]:
        _remember_maplestory_notice_in_state(state, notice, limit=limit)
    return state


def find_maplestory_notice_updates(
    notices: list[MapleStoryNotice],
    state: dict[str, Any] | None,
) -> list[MapleStoryNotice]:
    normalized = _normalize_maplestory_notice_state(state)
    stored_notices = normalized["notices"]
    updates: list[MapleStoryNotice] = []
    for notice in notices:
        stored = stored_notices.get(notice.notice_id)
        fingerprint = build_maplestory_notice_fingerprint(notice)
        if not isinstance(stored, dict) or stored.get("fingerprint") != fingerprint:
            updates.append(notice)
    return updates


async def refresh_sunday_maple_messages(
    bot: discord.Client,
    guild_id: int | None = None,
    *,
    fetch_event: FetchEvent | None = None,
) -> list[SundayMapleUpdateResult]:
    from util.celebration import get_celebration_channels

    channels = await get_celebration_channels(bot, guild_id)
    if not channels:
        return []

    fetch = fetch_event or fetch_sunday_maple_event
    try:
        event = await fetch()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("썬데이메이플 이벤트 조회 실패", exc_info=True)
        return [
            SundayMapleUpdateResult(
                guild_id=current_guild_id,
                channel_id=channel.id,
                status="error",
                action="fetch_failed",
                error=str(exc),
            )
            for current_guild_id, channel in channels.items()
        ]

    if event is None:
        return [
            SundayMapleUpdateResult(
                guild_id=current_guild_id,
                channel_id=channel.id,
                status="skipped",
                action="event_absent",
            )
            for current_guild_id, channel in channels.items()
        ]

    embeds = build_sunday_maple_event_embeds(event)
    if not embeds:
        return [
            SundayMapleUpdateResult(
                guild_id=current_guild_id,
                channel_id=channel.id,
                status="skipped",
                action="missing_images",
            )
            for current_guild_id, channel in channels.items()
        ]

    results: list[SundayMapleUpdateResult] = []
    for current_guild_id, channel in channels.items():
        try:
            sent_message = await channel.send(embeds=embeds)
            results.append(
                SundayMapleUpdateResult(
                    guild_id=current_guild_id,
                    channel_id=channel.id,
                    message_id=sent_message.id,
                    action="sent",
                )
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "썬데이메이플 공지 전송 실패: guild=%s channel=%s",
                current_guild_id,
                getattr(channel, "id", None),
                exc_info=True,
            )
            results.append(
                SundayMapleUpdateResult(
                    guild_id=current_guild_id,
                    channel_id=channel.id,
                    status="error",
                    error=str(exc),
                )
            )

    return results


async def refresh_maplestory_notice_messages(
    bot: discord.Client,
    *,
    fetch_notices: FetchNotices | None = None,
) -> list[MapleStoryNoticeUpdateResult]:
    from util.channel_settings import get_channels_by_purpose

    channels = await get_channels_by_purpose(MAPLESTORY_NOTICE_CHANNEL_TYPE)
    if not channels:
        return []

    fetch = fetch_notices or fetch_latest_maplestory_notices
    try:
        notices = await fetch()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("메이플스토리 공지 목록 조회 실패", exc_info=True)
        return [
            MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                status="error",
                action="fetch_failed",
                error=str(exc),
            )
            for guild_id, channel_id in channels.items()
        ]

    state = await _load_maplestory_notice_state()
    changed = False
    results: list[MapleStoryNoticeUpdateResult] = []

    for guild_id, channel_id in channels.items():
        guild_key = str(guild_id)
        guild_states = state.setdefault("guilds", {})
        if not isinstance(guild_states, dict):
            guild_states = {}
            state["guilds"] = guild_states

        guild_state = guild_states.get(guild_key)
        if guild_state is None:
            guild_states[guild_key] = maplestory_notice_state_from_notices(notices)
            changed = True
            results.append(
                MapleStoryNoticeUpdateResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    action="seeded",
                    status="skipped",
                )
            )
            continue

        updates = find_maplestory_notice_updates(notices, guild_state)
        if not updates:
            results.append(
                MapleStoryNoticeUpdateResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    action="unchanged",
                    status="skipped",
                )
            )
            continue

        target = await _resolve_text_channel(bot, channel_id)
        if target is None:
            results.append(
                MapleStoryNoticeUpdateResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    status="error",
                    action="channel_missing",
                    error="configured channel was not found",
                )
            )
            continue

        current_state = _normalize_maplestory_notice_state(guild_state)
        for notice in reversed(updates):
            try:
                await target.send(build_maplestory_notice_message(notice))
            except (discord.Forbidden, discord.HTTPException) as exc:
                logger.warning(
                    "메이플스토리 공지 전송 실패: guild=%s channel=%s notice=%s",
                    guild_id,
                    channel_id,
                    notice.notice_id,
                    exc_info=True,
                )
                results.append(
                    MapleStoryNoticeUpdateResult(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        notice_id=notice.notice_id,
                        status="error",
                        action="send_failed",
                        error=str(exc),
                    )
                )
                continue

            _remember_maplestory_notice_in_state(current_state, notice)
            guild_states[guild_key] = current_state
            changed = True
            results.append(
                MapleStoryNoticeUpdateResult(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    notice_id=notice.notice_id,
                    action="sent",
                )
            )

    if changed:
        await _save_maplestory_notice_state(state)

    return results


async def seed_maplestory_notice_state_for_guild(
    guild_id: int,
    *,
    fetch_notices: FetchNotices | None = None,
) -> int:
    fetch = fetch_notices or fetch_latest_maplestory_notices
    notices = await fetch()
    state = await _load_maplestory_notice_state()
    guild_states = state.setdefault("guilds", {})
    if not isinstance(guild_states, dict):
        guild_states = {}
        state["guilds"] = guild_states
    guild_states[str(int(guild_id))] = maplestory_notice_state_from_notices(notices)
    await _save_maplestory_notice_state(state)
    return len(notices)


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


def _normalize_text(value: str) -> str:
    return " ".join(unescape(value).split())


def _normalize_notice_text(value: str) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(r"\s+([,.!?])", r"\1", normalized)
    normalized = re.sub(r"([(/])\s+", r"\1", normalized)
    normalized = re.sub(r"\s+([)/])", r"\1", normalized)
    return normalized.strip()


def _build_notice_summary(value: str, max_length: int = 220) -> str:
    summary = _normalize_notice_text(value)
    for prefix in (
        "안녕하세요. 메이플스토리입니다.",
        "안녕하세요. 메이플스토리 입니다.",
    ):
        if summary.startswith(prefix):
            summary = summary[len(prefix) :].strip()
            break
    return _truncate_discord_text(summary, max_length)


def _truncate_discord_text(text: str, max_length: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def _attrs_to_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): value or "" for name, value in attrs}


def _has_class(attrs: dict[str, str], class_name: str) -> bool:
    return class_name in attrs.get("class", "").split()


def _canonical_notice_url(notice_id: str) -> str:
    return f"{MAPLESTORY_BASE_URL}/News/Notice/{notice_id}"


def _notice_id_from_href(href: str) -> str | None:
    match = re.search(r"/News/Notice(?:/All)?/(\d+)", href)
    return match.group(1) if match else None


def _normalize_maplestory_notice_state(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    notices: dict[str, Any] = {}
    recent_ids: list[str] = []
    if isinstance(state, dict):
        raw_notices = state.get("notices")
        if isinstance(raw_notices, dict):
            notices = {
                str(notice_id): value
                for notice_id, value in raw_notices.items()
                if isinstance(value, dict)
            }
        raw_recent_ids = state.get("recentNoticeIds")
        if isinstance(raw_recent_ids, list):
            recent_ids = [str(notice_id) for notice_id in raw_recent_ids if notice_id]
    return {"notices": notices, "recentNoticeIds": recent_ids}


def _remember_maplestory_notice_in_state(
    state: dict[str, Any],
    notice: MapleStoryNotice,
    *,
    limit: int = MAPLESTORY_NOTICE_STATE_LIMIT,
) -> None:
    normalized = _normalize_maplestory_notice_state(state)
    normalized["notices"][notice.notice_id] = {
        "fingerprint": build_maplestory_notice_fingerprint(notice),
        "title": notice.title,
        "category": notice.category,
    }
    recent_ids = [
        notice_id
        for notice_id in normalized["recentNoticeIds"]
        if notice_id != notice.notice_id
    ]
    recent_ids.insert(0, notice.notice_id)
    normalized["recentNoticeIds"] = recent_ids[:limit]
    known_ids = set(normalized["recentNoticeIds"])
    normalized["notices"] = {
        notice_id: value
        for notice_id, value in normalized["notices"].items()
        if notice_id in known_ids
    }
    state.clear()
    state.update(normalized)


async def _load_maplestory_notice_state() -> dict[str, Any]:
    from util.db import fetch_one

    row = await fetch_one(
        "SELECT setting_value FROM setting_data WHERE setting_key = %s",
        (MAPLESTORY_NOTICE_STATE_KEY,),
    )
    if not row:
        return {"guilds": {}}
    value = row.get("setting_value")
    if isinstance(value, dict):
        state = value
    elif isinstance(value, str) and value.strip():
        try:
            state = json.loads(value)
        except json.JSONDecodeError:
            state = {}
    else:
        state = {}
    guilds = state.get("guilds") if isinstance(state, dict) else None
    return {"guilds": guilds if isinstance(guilds, dict) else {}}


async def _save_maplestory_notice_state(state: dict[str, Any]) -> None:
    from util.db import execute_query

    await execute_query(
        "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
        (
            MAPLESTORY_NOTICE_STATE_KEY,
            json.dumps(state, ensure_ascii=False),
        ),
    )


async def _resolve_text_channel(bot: discord.Client, channel_id: int):
    target = bot.get_channel(int(channel_id))
    if target is None:
        try:
            target = await bot.fetch_channel(int(channel_id))
        except discord.DiscordException:
            return None
    if not hasattr(target, "send"):
        return None
    return target


class _MapleStoryNoticeListParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.notices: list[MapleStoryNotice] = []
        self._seen_notice_ids: set[str] = set()
        self._anchor_stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        normalized_tag = tag.lower()
        attrs_dict = _attrs_to_dict(attrs)
        if normalized_tag == "a":
            href = attrs_dict.get("href", "").strip()
            notice_id = _notice_id_from_href(href)
            if notice_id:
                self._anchor_stack.append(
                    {
                        "notice_id": notice_id,
                        "category": "",
                        "title_parts": [],
                        "span_depth": 0,
                    }
                )
                return

        if not self._anchor_stack:
            return

        current = self._anchor_stack[-1]
        if normalized_tag == "img":
            alt = attrs_dict.get("alt", "").strip()
            if alt.startswith("[") and alt.endswith("]"):
                current["category"] = alt
        elif normalized_tag == "span":
            current["span_depth"] = int(current.get("span_depth", 0)) + 1

    def handle_data(self, data: str):
        if not self._anchor_stack:
            return
        current = self._anchor_stack[-1]
        if int(current.get("span_depth", 0)) > 0:
            current["title_parts"].append(data)

    def handle_endtag(self, tag: str):
        normalized_tag = tag.lower()
        if not self._anchor_stack:
            return

        current = self._anchor_stack[-1]
        if normalized_tag == "span" and int(current.get("span_depth", 0)) > 0:
            current["span_depth"] = int(current["span_depth"]) - 1
            return

        if normalized_tag != "a":
            return

        anchor = self._anchor_stack.pop()
        notice_id = str(anchor["notice_id"])
        title = _normalize_notice_text("".join(anchor["title_parts"]))
        if not title or notice_id in self._seen_notice_ids:
            return

        self._seen_notice_ids.add(notice_id)
        self.notices.append(
            MapleStoryNotice(
                notice_id=notice_id,
                category=str(anchor.get("category") or ""),
                title=title,
                url=_canonical_notice_url(notice_id),
            )
        )


class _MapleStoryNoticeDetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.category = ""
        self._title_parts: list[str] = []
        self._body_parts: list[str] = []
        self._title_depth = 0
        self._body_depth = 0
        self._skip_depth = 0

    @property
    def title(self) -> str:
        return _normalize_notice_text("".join(self._title_parts))

    @property
    def body_text(self) -> str:
        return _normalize_notice_text(" ".join(self._body_parts))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        normalized_tag = tag.lower()
        attrs_dict = _attrs_to_dict(attrs)
        is_void = normalized_tag in _VOID_TAGS

        if normalized_tag in {"script", "style"}:
            self._skip_depth += 1
            return

        if _has_class(attrs_dict, "qs_title"):
            self._title_depth = 1
        elif self._title_depth and not is_void:
            self._title_depth += 1

        if _has_class(attrs_dict, "qs_text"):
            self._body_depth = 1
        elif self._body_depth and not is_void:
            self._body_depth += 1

        if self._title_depth and normalized_tag == "img" and not self.category:
            alt = attrs_dict.get("alt", "").strip()
            if alt.startswith("[") and alt.endswith("]"):
                self.category = alt

        if self._body_depth and normalized_tag in {"br", "div", "p", "tr", "li"}:
            self._body_parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str):
        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if normalized_tag in _VOID_TAGS:
            return
        if self._title_depth:
            self._title_depth -= 1
        if self._body_depth:
            self._body_depth -= 1

    def handle_data(self, data: str):
        if self._skip_depth:
            return
        if self._title_depth:
            self._title_parts.append(data)
        if self._body_depth:
            self._body_parts.append(data)


class _MapleStoryOngoingEventParser(HTMLParser):
    def __init__(self, target_title: str):
        super().__init__(convert_charrefs=True)
        self.target_title = _normalize_text(target_title)
        self.event_url: str | None = None
        self._anchor_stack: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag.lower() != "a" or self.event_url:
            return

        attrs_dict = _attrs_to_dict(attrs)
        href = attrs_dict.get("href", "").strip()
        data_title = _normalize_text(attrs_dict.get("data-title", ""))
        if data_title == self.target_title and self._is_ongoing_event_href(href):
            self.event_url = urljoin(MAPLESTORY_BASE_URL, href)
            return

        self._anchor_stack.append({"href": href, "text": []})

    def handle_data(self, data: str):
        if self._anchor_stack and not self.event_url:
            text_parts = self._anchor_stack[-1]["text"]
            if isinstance(text_parts, list):
                text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() != "a" or not self._anchor_stack or self.event_url:
            return

        anchor = self._anchor_stack.pop()
        href = str(anchor["href"])
        text = _normalize_text("".join(anchor["text"]))
        if text == self.target_title and self._is_ongoing_event_href(href):
            self.event_url = urljoin(MAPLESTORY_BASE_URL, href)

    @staticmethod
    def _is_ongoing_event_href(href: str) -> bool:
        return "/News/Event/Ongoing/" in href


class _MapleStoryEventDetailParser(HTMLParser):
    def __init__(self, event_url: str):
        super().__init__(convert_charrefs=True)
        self.event_url = event_url
        self.image_urls: list[str] = []
        self._seen_image_urls: set[str] = set()
        self._title_parts: list[str] = []
        self._period_parts: list[str] = []
        self._title_depth = 0
        self._period_depth = 0
        self._body_depth = 0

    @property
    def title(self) -> str:
        return _normalize_text("".join(self._title_parts))

    @property
    def period(self) -> str:
        return _normalize_text("".join(self._period_parts))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        normalized_tag = tag.lower()
        attrs_dict = _attrs_to_dict(attrs)
        is_void = normalized_tag in _VOID_TAGS

        if _has_class(attrs_dict, "qs_title"):
            self._title_depth = 1
        elif self._title_depth and not is_void:
            self._title_depth += 1

        if _has_class(attrs_dict, "event_date"):
            self._period_depth = 1
        elif self._period_depth and not is_void:
            self._period_depth += 1

        if _has_class(attrs_dict, "qs_text"):
            self._body_depth = 1
        elif self._body_depth and not is_void:
            self._body_depth += 1

        if self._body_depth and normalized_tag == "img":
            self._add_image(attrs_dict.get("src", ""))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str):
        normalized_tag = tag.lower()
        if normalized_tag in _VOID_TAGS:
            return

        if self._title_depth:
            self._title_depth -= 1
        if self._period_depth:
            self._period_depth -= 1
        if self._body_depth:
            self._body_depth -= 1

    def handle_data(self, data: str):
        if self._title_depth:
            self._title_parts.append(data)
        if self._period_depth:
            self._period_parts.append(data)

    def _add_image(self, src: str):
        if not src:
            return

        image_url = urljoin(self.event_url, src.strip())
        if image_url in self._seen_image_urls:
            return

        self._seen_image_urls.add(image_url)
        self.image_urls.append(image_url)
