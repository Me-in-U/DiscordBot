from __future__ import annotations

import discord

from .services import BalanceService


async def execute_transfer(
    interaction: discord.Interaction,
    balance: BalanceService,
    *,
    target_member: discord.Member,
    amount: int,
) -> None:
    guild_id = str(interaction.guild_id)
    sender_id = str(interaction.user.id)
    receiver_id = str(target_member.id)

    if sender_id == receiver_id:
        await interaction.response.send_message(
            "❌ 자기 자신에게는 송금 불가", ephemeral=True
        )
        return

    if target_member.bot:
        await interaction.response.send_message("❌ 봇에게는 송금 불가", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message(
            "❌ 금액은 0보다 커야 합니다.", ephemeral=True
        )
        return

    sender_balance = await balance.get_balance(guild_id, sender_id)
    if sender_balance < amount:
        await interaction.response.send_message(
            f"❌ 잔액 부족 (현재 {sender_balance:,}원)", ephemeral=True
        )
        return

    receiver_balance = await balance.get_balance(guild_id, receiver_id)
    await balance.set_balance(guild_id, sender_id, sender_balance - amount)
    await balance.set_balance(guild_id, receiver_id, receiver_balance + amount)

    embed = discord.Embed(
        title="💸 송금 완료",
        description=f"{interaction.user.mention} → {target_member.mention}",
        color=0x9B59B6,
    )
    embed.add_field(name="송금 금액", value=f"{amount:,}원", inline=False)
    embed.add_field(
        name="보낸 사람 잔액", value=f"{sender_balance - amount:,}원", inline=True
    )
    embed.add_field(
        name="받은 사람 잔액", value=f"{receiver_balance + amount:,}원", inline=True
    )

    await interaction.response.send_message(embed=embed)


__all__ = ["execute_transfer"]
