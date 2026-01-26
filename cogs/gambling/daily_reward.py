from __future__ import annotations

from datetime import datetime

import discord

from .constants import FINAL_BALANCE_LABEL, SEOUL_TZ
from .services import BalanceService

DAILY_AMOUNT = 10_000


async def grant_daily_money(
    interaction: discord.Interaction,
    balance: BalanceService,
) -> None:
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)

    if not await balance.can_use_daily(guild_id, user_id):
        await interaction.response.send_message(
            "❌ 오늘은 이미 돈을 받았습니다. 내일 다시 시도해주세요!",
            ephemeral=True,
        )
        return

    current = await balance.get_balance(guild_id, user_id)
    final_balance = current + DAILY_AMOUNT
    await balance.set_balance(guild_id, user_id, final_balance)

    today = datetime.now(SEOUL_TZ).date().isoformat()
    await balance.set_last_daily(guild_id, user_id, today)

    embed = discord.Embed(
        title="💰 일일 보상",
        description=f"{interaction.user.mention}님이 {DAILY_AMOUNT:,}원을 받았습니다!",
        color=0x00AA00,
        timestamp=datetime.now(SEOUL_TZ),
    )
    embed.add_field(
        name=FINAL_BALANCE_LABEL, value=f"{final_balance:,}원", inline=False
    )

    await interaction.response.send_message(embed=embed)


__all__ = ["grant_daily_money", "DAILY_AMOUNT"]
