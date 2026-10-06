from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import aiohttp

from util.guild.channel_settings import set_channel
from util.maplestory.events import (
    _load_maplestory_notice_state,
    _save_maplestory_notice_state,
    refresh_maplestory_notice_messages,
    seed_maplestory_notice_state_for_guild,
)
from util.maplestory.fetcher import MAPLESTORY_HEADERS
from util.maplestory.parser import MapleStoryNotice

LOSTARK_BASE_URL = "https://lostark.game.onstove.com"
LOSTARK_NOTICE_LIST_URL = f"{LOSTARK_BASE_URL}/News/Notice/List"
LOSTARK_NOTICE_CHANNEL_TYPE = "lostark_notice"
LOSTARK_NOTICE_STATE_KEY = "lostarkNoticeState"
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
# ponytail: one lock serializes polling and configuration; split by guild if needed.
_state_lock = asyncio.Lock()


class _NoticeParser(HTMLParser):
    def __init__(self, *, list_mode=True):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.fields = {"title": [], "category": [], "body": []}
        self.notices = {}
        self.url = None
        self.list_mode = list_mode

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        field = self.stack[-1][1] if self.stack else None
        classes = attrs.get("class", "").split()
        for name, markers in (
            ("title", {"list__title", "article__title"}),
            ("category", {"list__category", "article__category"}),
            ("body", {"article__data"}),
        ):
            if markers.intersection(classes):
                field = name
        if tag in {"script", "style"} or field == "ignore":
            field = "ignore"
        if tag == "a" and self.list_mode:
            url = urljoin(LOSTARK_BASE_URL, attrs.get("href", ""))
            parsed = urlsplit(url)
            if parsed.netloc == urlsplit(LOSTARK_BASE_URL).netloc and re.fullmatch(r"/News/Notice/(?:NoticeViews|Views)/\d+", parsed.path):
                self.url = url
                self.fields = {"title": [], "category": [], "body": []}
        if tag not in _VOID_TAGS:
            self.stack.append((tag, field))
        elif tag in {"br", "hr"}:
            self.handle_data(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data):
        field = self.stack[-1][1] if self.stack else None
        if field in self.fields:
            self.fields[field].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.url:
            title = self.text("title")
            if title:
                notice_id = urlsplit(self.url).path.rsplit("/", 1)[-1]
                self.notices[notice_id] = MapleStoryNotice(
                    notice_id=notice_id,
                    category=self.text("category"),
                    title=title,
                    url=f"{LOSTARK_BASE_URL}/News/Notice/Views/{notice_id}",
                    source_name="로스트아크",
                )
            self.url = None
        if tag not in _VOID_TAGS:
            self.handle_data(" ")
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

    def text(self, field):
        return " ".join("".join(self.fields[field]).split())


def parse_lostark_notice_list(html: str) -> list[MapleStoryNotice]:
    parser = _NoticeParser()
    parser.feed(html)
    notices = sorted(parser.notices.values(), key=lambda notice: int(notice.notice_id), reverse=True)
    if not notices:
        raise ValueError("로스트아크 공지 목록을 찾지 못했습니다.")
    return notices


def parse_lostark_notice_detail(html: str, notice: MapleStoryNotice) -> MapleStoryNotice:
    parser = _NoticeParser(list_mode=False)
    parser.feed(html)
    body = parser.text("body")
    if not body:
        raise ValueError(f"로스트아크 공지 본문을 찾지 못했습니다: {notice.notice_id}")
    return replace(notice, title=parser.text("title") or notice.title,
                   category=parser.text("category") or notice.category,
                   summary=body[:700], body_text=body)


async def fetch_latest_lostark_notices(fetch_html=None, *, limit: int = 20) -> list[MapleStoryNotice]:
    async with aiohttp.ClientSession(headers=MAPLESTORY_HEADERS, timeout=aiohttp.ClientTimeout(total=15), trust_env=False) as session:
        async def fetch(url):
            if fetch_html is not None:
                return await fetch_html(url)
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()

        notices = await asyncio.to_thread(parse_lostark_notice_list, await fetch(LOSTARK_NOTICE_LIST_URL))
        # A failed detail must not replace the saved body with an empty fingerprint.
        return [await asyncio.to_thread(parse_lostark_notice_detail, await fetch(notice.url), notice)
                for notice in notices[:limit]]


async def configure_lostark_notice_channel(guild_id: int, channel_id: int | None) -> None:
    async with _state_lock:
        if channel_id is None:
            await set_channel(guild_id, LOSTARK_NOTICE_CHANNEL_TYPE, None)
            state = await _load_maplestory_notice_state(LOSTARK_NOTICE_STATE_KEY)
            state["guilds"].pop(str(guild_id), None)
            await _save_maplestory_notice_state(state, LOSTARK_NOTICE_STATE_KEY)
        else:
            await seed_maplestory_notice_state_for_guild(
                guild_id, fetch_notices=fetch_latest_lostark_notices,
                state_key=LOSTARK_NOTICE_STATE_KEY,
            )
            await set_channel(guild_id, LOSTARK_NOTICE_CHANNEL_TYPE, channel_id)


async def run_lostark_notice_loop(bot):
    async with _state_lock:
        return await refresh_maplestory_notice_messages(
            bot, fetch_notices=fetch_latest_lostark_notices,
            channel_type=LOSTARK_NOTICE_CHANNEL_TYPE,
            state_key=LOSTARK_NOTICE_STATE_KEY,
        )
