from __future__ import annotations

import discord

from .services import BalanceService


async def show_ranking(
    interaction: discord.Interaction,
    balance: BalanceService,
    *,
    limit: int = 10,
) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "❌ 길드 정보가 없습니다.", ephemeral=True
        )
        return

    guild_id = str(guild.id)
    balances = balance.get_guild_balances(guild_id)
    if not balances:
        await interaction.response.send_message(
            "💤 아직 잔액 데이터가 없습니다. /돈줘 로 시작해보세요!", ephemeral=True
        )
        return

    sorted_entries = sorted(
        balances.items(), key=lambda kv: kv[1].get("balance", 0), reverse=True
    )
    requester_id = str(interaction.user.id)

    lines = []
    requester_rank = None
    for idx, (user_id, info) in enumerate(sorted_entries, start=1):
        balance_value = info.get("balance", 0)
        member = guild.get_member(int(user_id)) if user_id.isdigit() else None
        display_name = member.display_name if member else f"<@{user_id}>"
        line = f"{idx}위 — {display_name}: {balance_value:,}원"
        if user_id == requester_id:
            line = f"**{line}**"
            requester_rank = idx
        lines.append(line)

    embed = discord.Embed(
        title="💎 길드 자산 순위",
        description="\n".join(lines[:limit]),
        color=0x1ABC9C,
    )
    footer = (
        f"총 {len(sorted_entries)}명 | 내 순위: {requester_rank}위"
        if requester_rank
        else f"총 {len(sorted_entries)}명 | 순위 정보 없음"
    )
    embed.set_footer(text=footer)

    await interaction.response.send_message(embed=embed)


__all__ = ["show_ranking"]
