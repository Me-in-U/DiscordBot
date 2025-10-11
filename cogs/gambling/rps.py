from __future__ import annotations

import random

import discord

from .constants import BET_AMOUNT_REQUIRED, FINAL_BALANCE_LABEL
from .services import BalanceService


async def run_rock_paper_scissors(
    interaction: discord.Interaction,
    balance: BalanceService,
    *,
    choice_value: str,
    bet_amount: int,
) -> None:
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)

    if bet_amount <= 0:
        await interaction.response.send_message(BET_AMOUNT_REQUIRED, ephemeral=True)
        return

    current = balance.get_balance(guild_id, user_id)
    if current < bet_amount:
        await interaction.response.send_message(
            f"❌ 잔액 부족 (현재 {current:,}원)", ephemeral=True
        )
        return

    balance.set_balance(guild_id, user_id, current - bet_amount)

    bot_choice = random.choice(["가위", "바위", "보"])
    user_choice = choice_value
    if user_choice == bot_choice:
        result = "무승부"
        prize = bet_amount // 2
        color = 0xF1C40F
    elif (user_choice, bot_choice) in [
        ("가위", "보"),
        ("바위", "가위"),
        ("보", "바위"),
    ]:
        result = "승리"
        prize = bet_amount * 2
        color = 0x2ECC71
    else:
        result = "패배"
        prize = 0
        color = 0xE74C3C

    final_balance = balance.get_balance(guild_id, user_id) + prize
    balance.set_balance(guild_id, user_id, final_balance)

    embed = discord.Embed(title="✊✋✌️ 가위바위보", color=color)
    embed.add_field(name="당신", value=user_choice, inline=True)
    embed.add_field(name="봇", value=bot_choice, inline=True)
    embed.add_field(name="결과", value=result, inline=False)
    embed.add_field(name="배팅", value=f"{bet_amount:,}원", inline=True)
    embed.add_field(name="획득", value=f"{prize:,}원", inline=True)
    embed.add_field(
        name=FINAL_BALANCE_LABEL, value=f"{final_balance:,}원", inline=False
    )

    await interaction.response.send_message(embed=embed)


__all__ = ["run_rock_paper_scissors"]
