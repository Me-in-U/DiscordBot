from __future__ import annotations

import random

import discord

from .constants import FINAL_BALANCE_LABEL
from .services import BalanceService


async def run_instant_lottery(
    interaction: discord.Interaction,
    balance: BalanceService,
    *,
    ticket_price: int = 300,
) -> None:
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)

    current = balance.get_balance(guild_id, user_id)
    if current < ticket_price:
        await interaction.response.send_message(
            f"❌ 잔액 부족 (현재 {current:,}원 / 필요 {ticket_price}원)", ephemeral=True
        )
        return

    balance.set_balance(guild_id, user_id, current - ticket_price)

    roll = random.uniform(0, 100)
    prize, result_text, color = _determine_prize(roll)

    after_buy = balance.get_balance(guild_id, user_id)
    final_balance = after_buy + prize
    balance.set_balance(guild_id, user_id, final_balance)

    embed = discord.Embed(title="🎫 즉석복권", description=result_text, color=color)
    embed.add_field(name="구매", value=f"{ticket_price}원", inline=True)
    embed.add_field(name="당첨", value=f"{prize:,}원", inline=True)
    embed.add_field(
        name=FINAL_BALANCE_LABEL, value=f"{final_balance:,}원", inline=False
    )

    await interaction.response.send_message(embed=embed)


def _determine_prize(roll: float):
    if roll < 1.0:
        return 10000, "🎊 1만원 당첨!", 0xFFD700
    if roll < 2.7:
        return 3000, "🎉 3천원 당첨!", 0xC0C0C0
    if roll < 8.3:
        return 1000, "🎈 1천원 당첨!", 0xCD7F32
    if roll < 20.0:
        return 300, "😊 300원 (본전)", 0x3498DB
    return 0, "😢 꽝...", 0x95A5A6


__all__ = ["run_instant_lottery"]
