from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

import aiohttp


MAPLESTORY_BASE_URL = "https://maplestory.nexon.com"
MAPLESTORY_ONGOING_EVENT_LIST_URL = f"{MAPLESTORY_BASE_URL}/News/Event/Ongoing"
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


@dataclass(frozen=True, slots=True)
class MapleStoryEvent:
    title: str
    url: str
    period: str = ""
    image_urls: list[str] = field(default_factory=list)


def parse_maplestory_ongoing_event_url(
    html: str,
    target_title: str = SUNDAY_MAPLE_EVENT_TITLE,
) -> str | None:
    parser = _MapleStoryOngoingEventParser(target_title)
    parser.feed(html)
    return parser.event_url


def parse_maplestory_event_detail(html: str, event_url: str) -> MapleStoryEvent:
    parser = _MapleStoryEventDetailParser(event_url)
    parser.feed(html)
    return MapleStoryEvent(
        title=parser.title or SUNDAY_MAPLE_EVENT_TITLE,
        url=event_url,
        period=parser.period,
        image_urls=parser.image_urls,
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


def _attrs_to_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): value or "" for name, value in attrs}


def _has_class(attrs: dict[str, str], class_name: str) -> bool:
    return class_name in attrs.get("class", "").split()


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
