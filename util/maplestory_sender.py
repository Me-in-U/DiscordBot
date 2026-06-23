from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import discord

from util.maplestory_parser import MapleStoryEvent, MapleStoryNotice


logger = logging.getLogger(__name__)


MAPLESTORY_NOTICE_SUMMARY_MODEL = "gpt-5.4-mini"
MAPLESTORY_NOTICE_SUMMARY_MAX_OUTPUT_TOKENS = 220
MAPLESTORY_NOTICE_SUMMARY_LINE_LIMIT = 45
MAPLESTORY_NOTICE_SUMMARY_INSTRUCTIONS = (
    "너는 메이플스토리 공식 공지를 Discord 임베드 알림용으로 요약한다.\n"
    "한국어로 정확히 3줄만 출력한다.\n"
    "각 줄은 35자 안팎으로 짧고 밀도 있게 쓴다.\n"
    "원문에 없는 날짜, 보상, 원인을 만들지 않는다.\n"
    "인사말, 사과문, 중복 표현은 버리고 핵심 일정, 대상, 조치만 남긴다.\n"
    "번호, 불릿, 제목, 머리말 없이 줄바꿈으로만 구분한다."
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
    return "\n".join(
        [
            f"분류: {notice.category or '공지'}",
            f"제목: {notice.title}",
            f"링크: {notice.url}",
            "본문:",
            notice.summary or notice.title,
        ]
    )


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
        if len(lines) == 3:
            break

    if len(lines) < 3:
        for fallback_line in _fallback_maplestory_notice_summary_lines(notice):
            if fallback_line in lines:
                continue
            lines.append(fallback_line)
            if len(lines) == 3:
                break

    return lines[:3]


def _clean_maplestory_notice_summary_line(line: str) -> str:
    cleaned = " ".join((line or "").strip().split())
    cleaned = re.sub(r"^(?:[-*•·]+|\d+[.)])\s*", "", cleaned)
    return cleaned.strip(" -")


def _fallback_maplestory_notice_summary_lines(notice: MapleStoryNotice) -> list[str]:
    source = notice.summary or notice.title
    source = _strip_notice_greeting(source)
    candidates = [
        _clean_maplestory_notice_summary_line(part)
        for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", source)
    ]
    lines = [
        _truncate_discord_text(candidate, MAPLESTORY_NOTICE_SUMMARY_LINE_LIMIT)
        for candidate in candidates
        if candidate
    ]

    fallback_candidates = [
        notice.title,
        f"{notice.category or '[공지]'} 공지입니다.",
        "상세 내용은 공식 공지에서 확인해 주세요.",
    ]
    for candidate in fallback_candidates:
        line = _truncate_discord_text(
            _clean_maplestory_notice_summary_line(candidate),
            MAPLESTORY_NOTICE_SUMMARY_LINE_LIMIT,
        )
        if line and line not in lines:
            lines.append(line)
        if len(lines) >= 3:
            break

    return lines[:3]


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
