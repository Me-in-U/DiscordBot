from __future__ import annotations

import discord

from .services import BalanceService


async def show_balance(
    interaction: discord.Interaction,
    balance: BalanceService,
) -> None:
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)
    current = balance.get_balance(guild_id, user_id)

    embed = discord.Embed(
        title="💵 잔액 조회",
        description=f"{interaction.user.mention}님의 잔액",
        color=0x3498DB,
    )
    embed.add_field(name="보유 금액", value=f"{current:,}원", inline=False)

    await interaction.response.send_message(embed=embed)


__all__ = ["show_balance"]
