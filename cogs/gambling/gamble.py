from __future__ import annotations

import random

import discord

from .constants import BET_AMOUNT_REQUIRED, FINAL_BALANCE_LABEL, SEOUL_TZ
from .services import BalanceService
from .operations import financial_operation


@financial_operation
async def run_gamble(
    interaction: discord.Interaction,
    balance: BalanceService,
    *,
    bet_amount: int,
) -> None:
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)

    if bet_amount <= 0:
        await interaction.response.send_message(BET_AMOUNT_REQUIRED, ephemeral=True)
        return

    current = await balance.get_balance(guild_id, user_id)
    if current < bet_amount:
        await interaction.response.send_message(
            f"❌ 잔액 부족 (현재 {current:,}원)", ephemeral=True
        )
        return

    await balance.set_balance(guild_id, user_id, current - bet_amount)

    win_chance = random.randint(30, 70)
    roll = random.randint(1, 100)
    roulette_visual = _build_roulette(win_chance, roll)
    is_win = roll <= win_chance

    if is_win:
        prize = bet_amount * 2
        result_text = "🎉 당첨!"
        color = 0x2ECC71
    else:
        prize = 0
        result_text = "💥 실패..."
        color = 0xE74C3C

    after_bet = await balance.get_balance(guild_id, user_id)
    final_balance = after_bet + prize
    await balance.set_balance(guild_id, user_id, final_balance)
    await balance.add_result(guild_id, user_id, is_win)
    wins, losses, rate = await balance.get_stats(guild_id, user_id)

    embed = discord.Embed(
        title="🎰 도박 결과",
        description=result_text,
        color=color,
        timestamp=interaction.created_at or None,
    )
    if embed.timestamp is None:
        embed.timestamp = _current_timestamp()
    embed.add_field(name="당첨 확률", value=f"{win_chance}%", inline=True)
    embed.add_field(name="룰렛", value=roulette_visual, inline=False)
    embed.add_field(
        name="전적",
        value=f"승 {wins} · 패 {losses} (승률 {rate:.1f}%)",
        inline=False,
    )
    footer_text = f"배팅 {bet_amount:,}원 • 획득 {prize:,}원 • 잔액 {final_balance:,}원"
    avatar_url = (
        interaction.user.display_avatar.url if interaction.user.display_avatar else None
    )
    if avatar_url:
        embed.set_footer(text=footer_text, icon_url=avatar_url)
    else:
        embed.set_footer(text=footer_text)

    await interaction.response.send_message(embed=embed)


def _build_roulette(chance: int, value: int, width: int = 30) -> str:
    if width < 10:
        width = 10
    step = 100 / width
    pointer_index = min(width - 1, int((value - 1) / step))
    win_last_index = int((chance - 1) / step)
    bar_chars = ["█" if i <= win_last_index else "░" for i in range(width)]
    bar_line = "".join(bar_chars)
    pointer_line = [" "] * width
    pointer_line[pointer_index] = "▲"
    return f"`{bar_line}`\n`{''.join(pointer_line)}`\n"


def _current_timestamp():
    from datetime import datetime

    return datetime.now(SEOUL_TZ)


__all__ = ["run_gamble"]
