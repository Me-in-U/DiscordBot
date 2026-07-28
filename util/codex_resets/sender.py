from __future__ import annotations

import discord

from util.codex_resets.fetcher import CodexResetEvent


CODEX_RESETS_SITE_URL = "https://codex-resets.com/"
CODEX_RESET_DESCRIPTION_LIMIT = 4000


def build_codex_reset_embed(event: CodexResetEvent) -> discord.Embed:
    embed = discord.Embed(
        title="Codex 사용량 리셋 감지",
        url=event.tweet_url,
        description=_truncate_text(event.text, CODEX_RESET_DESCRIPTION_LIMIT),
        color=discord.Color.green(),
        timestamp=event.announced_at,
    )
    embed.set_author(name="Codex Resets")
    embed.add_field(
        name="원문",
        value=f"[X에서 보기]({event.tweet_url})",
        inline=True,
    )
    embed.add_field(
        name="추적기",
        value=f"[codex-resets.com]({CODEX_RESETS_SITE_URL})",
        inline=True,
    )
    embed.set_footer(text="출처: codex-resets.com 비공식 추적기")
    return embed


async def send_codex_reset_notification(
    target: object,
    event: CodexResetEvent,
) -> int | None:
    message = await target.send(embed=build_codex_reset_embed(event))
    message_id = getattr(message, "id", None)
    return int(message_id) if message_id is not None else None


def _truncate_text(text: str, max_length: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."
