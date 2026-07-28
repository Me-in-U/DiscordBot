from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable

import aiohttp

from util.earthquake.jma_eew import JmaEewEvent


GOOGLE_TRANSLATE_URL = (
    "https://translate.googleapis.com/translate_a/single"
)
TRANSLATION_RETRY_SECONDS = 10 * 60
JAPANESE_TEXT_PATTERN = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]"
)

logger = logging.getLogger(__name__)
TranslateTexts = Callable[
    [tuple[str, ...]],
    Awaitable[dict[str, str]],
]

_translation_cache: dict[str, str] = {}
_translation_lock = asyncio.Lock()
_translation_retry_at = 0.0


async def translate_jma_eew_terms(
    event: JmaEewEvent,
    *,
    translate_texts: TranslateTexts | None = None,
) -> dict[str, str]:
    texts = _unique_japanese_texts(
        [
            event.hypocenter,
            *(
                text
                for area in event.warn_areas
                for text in (area.name, area.arrival_status)
            ),
        ]
    )
    if not texts:
        return {}

    translate = translate_texts or translate_japanese_texts
    return await translate(texts)


async def translate_japanese_texts(
    texts: tuple[str, ...],
) -> dict[str, str]:
    global _translation_retry_at

    requested = _unique_japanese_texts(texts)
    if not requested:
        return {}

    uncached = tuple(
        text for text in requested if text not in _translation_cache
    )
    if not uncached:
        return _cached_translations(requested)

    async with _translation_lock:
        uncached = tuple(
            text for text in requested if text not in _translation_cache
        )
        if not uncached:
            return _cached_translations(requested)
        if time.monotonic() < _translation_retry_at:
            return _cached_translations(requested)

        try:
            translated = await _request_google_translations(uncached)
        except (
            GoogleTranslationError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,
        ) as exc:
            _translation_retry_at = (
                time.monotonic() + TRANSLATION_RETRY_SECONDS
            )
            logger.warning(
                "지진 일본어 Google 번역 실패: %s",
                exc,
            )
            return _cached_translations(requested)

        _translation_cache.update(translated)
        _translation_retry_at = 0.0
        return _cached_translations(requested)


async def _request_google_translations(
    texts: tuple[str, ...],
) -> dict[str, str]:
    timeout = aiohttp.ClientTimeout(total=6, connect=3)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        values = await asyncio.gather(
            *(
                _request_google_translation(session, text)
                for text in texts
            )
        )
    return {
        source: translated
        for source, translated in zip(texts, values, strict=True)
        if translated and translated != source
    }


async def _request_google_translation(
    session: aiohttp.ClientSession,
    text: str,
) -> str:
    async with session.get(
        GOOGLE_TRANSLATE_URL,
        params={
            "client": "gtx",
            "sl": "ja",
            "tl": "ko",
            "dt": "t",
            "q": text,
        },
    ) as response:
        if response.status != 200:
            raise GoogleTranslationError(f"HTTP {response.status}")
        payload = await response.json(content_type=None)
    return _extract_google_translation(payload)


def _extract_google_translation(payload: object) -> str:
    if not isinstance(payload, list) or not payload:
        raise ValueError("Google 번역 응답 형식이 올바르지 않습니다.")
    segments = payload[0]
    if not isinstance(segments, list):
        raise ValueError("Google 번역 문장 목록이 없습니다.")

    translated_parts: list[str] = []
    for segment in segments:
        if (
            isinstance(segment, list)
            and segment
            and isinstance(segment[0], str)
        ):
            translated_parts.append(segment[0])
    translated = html.unescape("".join(translated_parts)).strip()
    if not translated:
        raise ValueError("Google 번역 결과가 비어 있습니다.")
    return translated


def _unique_japanese_texts(texts: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in texts:
        text = str(value or "").strip()
        if (
            not text
            or text in seen
            or JAPANESE_TEXT_PATTERN.search(text) is None
        ):
            continue
        unique.append(text)
        seen.add(text)
    return tuple(unique)


def _cached_translations(
    texts: tuple[str, ...],
) -> dict[str, str]:
    return {
        text: _translation_cache[text]
        for text in texts
        if text in _translation_cache
    }


class GoogleTranslationError(RuntimeError):
    pass
