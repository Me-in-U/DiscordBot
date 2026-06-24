from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import discord

from util.maplestory.parser import MapleStoryEvent, MapleStoryNotice


logger = logging.getLogger(__name__)


MAPLESTORY_NOTICE_SUMMARY_MODEL = "gpt-5.4-mini"
MAPLESTORY_NOTICE_SUMMARY_MAX_OUTPUT_TOKENS = 320
MAPLESTORY_NOTICE_SUMMARY_LINE_LIMIT = 90
MAPLESTORY_NOTICE_SUMMARY_MIN_LINES = 3
MAPLESTORY_NOTICE_SUMMARY_MAX_LINES = 4
MAPLESTORY_NOTICE_FULL_BODY_LIMIT = 1200
MAPLESTORY_NOTICE_IMPORTANT_BODY_LIMIT = 2200
MAPLESTORY_NOTICE_IMPORTANT_BLOCK_LIMIT = 6
MAPLESTORY_NOTICE_SUMMARY_INSTRUCTIONS = (
    "너는 메이플스토리 공식 공지를 Discord 임베드 알림용으로 재밌게 요약한다.\n"
    "한국어로 3~4줄만 출력한다.\n"
    "말투는 '반갑다 용사들아', '점검이 왔다', '알아서 원문 확인해라'처럼 건방지고 직설적인 반말로 쓴다.\n"
    "욕설, 혐오, 특정 집단 비하, 성적 표현은 쓰지 않는다.\n"
    "원문에 없는 날짜, 시간, 대상, 보상, 원인을 만들지 않는다.\n"
    "인사말, 사과문, 중복 표현은 버리고 핵심 일정, 대상, 영향, 보상만 남긴다.\n"
    "월드나 채널별 시간이 복잡하면 '월드별로 다르니 원문 확인해라'로 압축한다.\n"
    "번호, 불릿, 제목, 머리말 없이 줄바꿈으로만 구분한다."
)
_NOTICE_SECTION_LABEL_PATTERN = re.compile(r"\[\s*([^\]]{1,60})\s*\]")
_IMPORTANT_NOTICE_LABEL_KEYWORDS = (
    "작업일시",
    "작업대상",
    "작업내역",
    "적용일시",
    "전체월드작업내역",
    "점검일정",
    "점검내용",
    "점검시간",
    "작업영향",
    "보상",
    "기간",
    "지급",
    "수령",
)
_IMPORTANT_NOTICE_DIRECT_PHRASES = (
    "점검시간과 작업영향",
    "점검 시간과 작업 영향",
)
GenerateText = Callable[[str, str, str, int | None], str]
SummarizeNotice = Callable[[MapleStoryNotice], Awaitable[list[str]]]


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


async def summarize_maplestory_notice_with_openai(
    notice: MapleStoryNotice,
    *,
    generate_text: GenerateText | None = None,
) -> list[str]:
    text_generator = generate_text
    if text_generator is None:
        try:
            text_generator = _load_openai_text_generator()
        except Exception:
            logger.warning("메이플스토리 공지 OpenAI 요약기 로딩 실패", exc_info=True)
            return _fallback_maplestory_notice_summary_lines(notice)

    try:
        output = await asyncio.to_thread(
            text_generator,
            _build_maplestory_notice_summary_input(notice),
            MAPLESTORY_NOTICE_SUMMARY_INSTRUCTIONS,
            MAPLESTORY_NOTICE_SUMMARY_MODEL,
            MAPLESTORY_NOTICE_SUMMARY_MAX_OUTPUT_TOKENS,
        )
    except Exception:
        logger.warning(
            "메이플스토리 공지 OpenAI 요약 실패: notice=%s",
            notice.notice_id,
            exc_info=True,
        )
        return _fallback_maplestory_notice_summary_lines(notice)

    return _coerce_maplestory_notice_summary_lines(output, notice)


def build_maplestory_notice_embed(
    notice: MapleStoryNotice,
    summary_lines: list[str],
) -> discord.Embed:
    lines = _coerce_maplestory_notice_summary_lines("\n".join(summary_lines), notice)
    embed = discord.Embed(
        title=_truncate_discord_text(notice.title, 256),
        url=notice.url,
        description="\n".join(lines),
        color=_maplestory_notice_color(notice),
    )
    embed.set_author(name="메이플스토리 공지")
    if notice.category:
        embed.add_field(name="분류", value=notice.category, inline=True)
    embed.add_field(name="원문", value=f"[바로가기]({notice.url})", inline=True)
    embed.set_footer(text="출처: 메이플스토리 공식 공지")
    return embed


async def send_sunday_maple_event_to_channels(
    channels: dict[int, object],
    event: MapleStoryEvent,
) -> list[SundayMapleUpdateResult]:
    embeds = build_sunday_maple_event_embeds(event)
    if not embeds:
        return [
            SundayMapleUpdateResult(
                guild_id=current_guild_id,
                channel_id=getattr(channel, "id", None),
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
                    channel_id=getattr(channel, "id", None),
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
                    channel_id=getattr(channel, "id", None),
                    status="error",
                    error=str(exc),
                )
            )

    return results


async def send_maplestory_notice_to_channel(
    target: object,
    *,
    guild_id: int,
    channel_id: int,
    notice: MapleStoryNotice,
    summarize_notice: SummarizeNotice | None = None,
) -> MapleStoryNoticeUpdateResult:
    summarize = summarize_notice or summarize_maplestory_notice_with_openai
    try:
        summary_lines = await summarize(notice)
    except Exception:
        logger.warning(
            "메이플스토리 공지 요약 실패: guild=%s channel=%s notice=%s",
            guild_id,
            channel_id,
            notice.notice_id,
            exc_info=True,
        )
        summary_lines = _fallback_maplestory_notice_summary_lines(notice)

    try:
        await target.send(embed=build_maplestory_notice_embed(notice, summary_lines))
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning(
            "메이플스토리 공지 전송 실패: guild=%s channel=%s notice=%s",
            guild_id,
            channel_id,
            notice.notice_id,
            exc_info=True,
        )
        return MapleStoryNoticeUpdateResult(
            guild_id=guild_id,
            channel_id=channel_id,
            notice_id=notice.notice_id,
            status="error",
            action="send_failed",
            error=str(exc),
        )

    return MapleStoryNoticeUpdateResult(
        guild_id=guild_id,
        channel_id=channel_id,
        notice_id=notice.notice_id,
        action="sent",
    )


async def resolve_text_channel(bot: discord.Client, channel_id: int):
    target = bot.get_channel(int(channel_id))
    if target is None:
        try:
            target = await bot.fetch_channel(int(channel_id))
        except discord.DiscordException:
            return None
    if not hasattr(target, "send"):
        return None
    return target


def _truncate_discord_text(text: str, max_length: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def _load_openai_text_generator() -> GenerateText:
    from api.chatGPT import generate_text_model

    return generate_text_model


def _build_maplestory_notice_summary_input(notice: MapleStoryNotice) -> str:
    source_label, body = _select_maplestory_notice_summary_body(notice)
    return "\n".join(
        [
            f"분류: {notice.category or '공지'}",
            f"제목: {notice.title}",
            f"링크: {notice.url}",
            f"본문 발췌 방식: {source_label}",
            "본문:",
            body,
        ]
    )


def _select_maplestory_notice_summary_body(notice: MapleStoryNotice) -> tuple[str, str]:
    body = _normalize_summary_source(
        getattr(notice, "body_text", "") or notice.summary or notice.title
    )
    if len(body) <= MAPLESTORY_NOTICE_FULL_BODY_LIMIT:
        return "전문", body

    important_blocks = _extract_important_notice_blocks(body)
    if important_blocks:
        return "중요 블록", _fit_notice_summary_blocks(important_blocks)

    return "긴 전문 앞부분", _truncate_discord_text(
        body,
        MAPLESTORY_NOTICE_IMPORTANT_BODY_LIMIT,
    )


def _normalize_summary_source(text: str) -> str:
    return " ".join((text or "").split())


def _extract_important_notice_blocks(body: str) -> list[str]:
    markers = _find_notice_section_markers(body)
    if not markers:
        return []

    blocks: list[str] = []
    seen_blocks: set[str] = set()
    for index, (start, label) in enumerate(markers):
        if not _is_important_notice_label(label):
            continue

        end = markers[index + 1][0] if index + 1 < len(markers) else len(body)
        block = body[start:end].strip()
        if not block or block in seen_blocks:
            continue

        seen_blocks.add(block)
        blocks.append(block)
        if len(blocks) == MAPLESTORY_NOTICE_IMPORTANT_BLOCK_LIMIT:
            break

    return blocks


def _find_notice_section_markers(body: str) -> list[tuple[int, str]]:
    markers: list[tuple[int, str]] = []
    for match in _NOTICE_SECTION_LABEL_PATTERN.finditer(body):
        markers.append((match.start(), match.group(1)))

    for phrase in _IMPORTANT_NOTICE_DIRECT_PHRASES:
        start = 0
        while True:
            index = body.find(phrase, start)
            if index < 0:
                break
            markers.append((index, phrase))
            start = index + len(phrase)

    deduped: dict[int, str] = {}
    for start, label in markers:
        deduped.setdefault(start, label)
    return sorted(deduped.items(), key=lambda item: item[0])


def _is_important_notice_label(label: str) -> bool:
    compact = re.sub(r"\s+", "", label or "")
    return any(keyword in compact for keyword in _IMPORTANT_NOTICE_LABEL_KEYWORDS)


def _fit_notice_summary_blocks(blocks: list[str]) -> str:
    selected: list[str] = []
    used = 0
    for block in blocks:
        separator_length = 1 if selected else 0
        remaining = MAPLESTORY_NOTICE_IMPORTANT_BODY_LIMIT - used - separator_length
        if remaining <= 0:
            break

        normalized = _normalize_summary_source(block)
        if len(normalized) > remaining:
            normalized = _truncate_discord_text(normalized, remaining)

        if normalized:
            selected.append(normalized)
            used += len(normalized) + separator_length

    return "\n".join(selected)


def _coerce_maplestory_notice_summary_lines(
    text: str,
    notice: MapleStoryNotice,
) -> list[str]:
    lines: list[str] = []
    for raw_line in (text or "").replace("\r", "\n").split("\n"):
        line = _clean_maplestory_notice_summary_line(raw_line)
        if not line:
            continue
        lines.append(_truncate_discord_text(line, MAPLESTORY_NOTICE_SUMMARY_LINE_LIMIT))
        if len(lines) == MAPLESTORY_NOTICE_SUMMARY_MAX_LINES:
            break

    if len(lines) < MAPLESTORY_NOTICE_SUMMARY_MIN_LINES:
        for fallback_line in _fallback_maplestory_notice_summary_lines(notice):
            if fallback_line in lines:
                continue
            lines.append(fallback_line)
            if len(lines) == MAPLESTORY_NOTICE_SUMMARY_MIN_LINES:
                break

    return lines[:MAPLESTORY_NOTICE_SUMMARY_MAX_LINES]


def _clean_maplestory_notice_summary_line(line: str) -> str:
    cleaned = " ".join((line or "").strip().split())
    cleaned = re.sub(r"^(?:[-*•·]+|\d+[.)])\s*", "", cleaned)
    return cleaned.strip(" -")


def _fallback_maplestory_notice_summary_lines(notice: MapleStoryNotice) -> list[str]:
    source = _strip_notice_greeting(
        _normalize_summary_source(
            getattr(notice, "body_text", "") or notice.summary or notice.title
        )
    )
    source_blocks = _extract_important_notice_blocks(source)
    candidates = source_blocks or [
        _clean_maplestory_notice_summary_line(part)
        for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", source)
    ]

    lines = [_spicy_notice_intro_line(notice)]
    for candidate in candidates:
        fact_line = _spicy_notice_fact_line(candidate)
        if not fact_line or fact_line in lines:
            continue
        lines.append(fact_line)
        if len(lines) == MAPLESTORY_NOTICE_SUMMARY_MAX_LINES - 1:
            break

    closing = "자세한 건 원문 보고 헛걸음하지 마라."
    if closing not in lines:
        lines.append(closing)

    return [
        _truncate_discord_text(line, MAPLESTORY_NOTICE_SUMMARY_LINE_LIMIT)
        for line in lines[:MAPLESTORY_NOTICE_SUMMARY_MAX_LINES]
    ]


def _spicy_notice_intro_line(notice: MapleStoryNotice) -> str:
    label = f"{notice.category} {notice.title}"
    if "점검" in label or "패치" in label:
        return "반갑다 용사들아, 점검 공지 떴다."
    if "보상" in label:
        return "반갑다 용사들아, 보상 공지 떴다."
    return "반갑다 용사들아, 새 공지 떴다."


def _spicy_notice_fact_line(text: str) -> str:
    cleaned = _clean_maplestory_notice_summary_line(text)
    cleaned = re.sub(r"^\[[^\]]+\]\s*", "", cleaned).strip()
    if not cleaned:
        return ""
    return f"핵심은 {cleaned}"


def _strip_notice_greeting(text: str) -> str:
    stripped = (text or "").strip()
    for prefix in (
        "안녕하세요. 메이플스토리입니다.",
        "안녕하세요. 메이플스토리 입니다.",
    ):
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped


def _maplestory_notice_color(notice: MapleStoryNotice) -> discord.Color:
    label = f"{notice.category} {notice.title}"
    if "점검" in label:
        return discord.Color.orange()
    if "패치" in label:
        return discord.Color.gold()
    return discord.Color.blue()
