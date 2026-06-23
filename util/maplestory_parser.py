from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


MAPLESTORY_BASE_URL = "https://maplestory.nexon.com"
MAPLESTORY_ONGOING_EVENT_LIST_URL = f"{MAPLESTORY_BASE_URL}/News/Event/Ongoing"
MAPLESTORY_NOTICE_LIST_URL = f"{MAPLESTORY_BASE_URL}/News/Notice"
SUNDAY_MAPLE_EVENT_TITLE = "스페셜 썬데이 메이플"
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
    return _truncate_text(summary, max_length)


def _truncate_text(text: str, max_length: int) -> str:
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
