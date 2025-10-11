from __future__ import annotations

import random

import discord

from .services import BalanceService
from .sprinkle import SprinkleView, build_sprinkle_embed


async def run_sprinkle(
    interaction: discord.Interaction,
    balance: BalanceService,
    *,
    total_amount: int,
    people: int,
) -> None:
    timeout = 300
    guild_id = str(interaction.guild_id)
    sender_id = str(interaction.user.id)

    if total_amount <= 0 or people <= 0:
        await interaction.response.send_message(
            "❌ 금액과 인원은 0보다 커야 합니다.", ephemeral=True
        )
        return

    if people > total_amount:
        await interaction.response.send_message(
            (
                f"❌ 인원({people})이 금액({total_amount})보다 많습니다. "
                "최소 1원씩 지급하려면 인원을 줄여주세요."
            ),
            ephemeral=True,
        )
        return

    sender_balance = balance.get_balance(guild_id, sender_id)
    if sender_balance < total_amount:
        await interaction.response.send_message(
            f"❌ 잔액 부족 (현재 {sender_balance:,}원)", ephemeral=True
        )
        return

    balance.set_balance(guild_id, sender_id, sender_balance - total_amount)

    parts = _split_amount_randomly(total_amount, people)
    embed = build_sprinkle_embed(interaction.user, total_amount, people)
    view = SprinkleView(
        balance=balance,
        parts_list=parts,
        sender_user=interaction.user,
        guild_id=guild_id,
        timeout=timeout,
    )

    await interaction.response.send_message(embed=embed, view=view)
    try:
        sent = await interaction.original_response()
        view.original_message = sent
    except Exception:
        pass


def _split_amount_randomly(total_amount: int, people: int) -> list[int]:
    if people <= 1:
        return [total_amount]

    cuts = sorted(random.sample(range(1, total_amount), people - 1))
    parts: list[int] = []
    prev = 0
    for cut in cuts + [total_amount]:
        parts.append(cut - prev)
        prev = cut
    random.shuffle(parts)
    return parts


__all__ = ["run_sprinkle"]
