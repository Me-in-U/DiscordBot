from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Dict, List, Tuple

import discord

from .constants import SEOUL_TZ
from .services import BalanceService


class WeeklyLotteryView(discord.ui.View):
    """주간 복주머니 인터랙션 뷰."""

    def __init__(
        self,
        *,
        balance: BalanceService,
        prize_map: List[int],
        guild_id: str,
        timeout: int = 3600,
    ):
        super().__init__(timeout=timeout)
        self._balance = balance
        self.prize_map = list(prize_map)
        self.guild_id = guild_id
        self.lock = asyncio.Lock()
        self.original_message: discord.Message | None = None
        self.btn_states: List[Dict[str, object]] = [
            {"claimed": False, "user": None, "prize": prize} for prize in prize_map
        ]
        self.claimed: Dict[int, Tuple[int, int]] = {}

        for index in range(len(prize_map)):
            self.add_item(self._make_button(index))

    def _make_button(self, idx: int) -> discord.ui.Button:
        label = f"복주머니 {idx + 1}"
        button = discord.ui.Button(
            label=label, style=discord.ButtonStyle.primary, custom_id=f"lottery_{idx}"
        )

        async def callback(interaction: discord.Interaction) -> None:
            async with self.lock:
                await self._handle_button_interaction(interaction, idx, button)

        button.callback = callback
        return button

    async def _handle_button_interaction(
        self,
        interaction: discord.Interaction,
        idx: int,
        button: discord.ui.Button,
    ) -> None:
        user_id = interaction.user.id
        if user_id in self.claimed:
            await interaction.response.send_message(
                "❌ 이미 참여하셨습니다.", ephemeral=True
            )
            return
        if self.btn_states[idx]["claimed"]:
            await interaction.response.send_message(
                "❌ 이미 선택된 복주머니입니다.", ephemeral=True
            )
            return

        prize = int(self.btn_states[idx]["prize"])
        self.btn_states[idx]["claimed"] = True
        self.btn_states[idx]["user"] = user_id
        self.claimed[user_id] = (idx, prize)

        button.disabled = True
        if prize > 0:
            button.label = f"🎉 {prize:,}원!"
            button.style = discord.ButtonStyle.success
            current = self._balance.get_balance(self.guild_id, str(user_id))
            self._balance.set_balance(self.guild_id, str(user_id), current + prize)
            await interaction.response.send_message(
                f"🎉 축하합니다! {prize:,}원을 획득했습니다!", ephemeral=True
            )
        else:
            button.label = "꽝"
            button.style = discord.ButtonStyle.secondary
            await interaction.response.send_message(
                "😢 아쉽게도 꽝입니다! 다음 기회에...", ephemeral=True
            )

        await self._update_embed(interaction)

        winners = sum(
            1 for state in self.btn_states if state["prize"] > 0 and state["claimed"]
        )
        if winners >= len([p for p in self.prize_map if p > 0]):
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            await self._update_embed(interaction, finished=True)
            self.stop()

    async def _update_embed(
        self,
        interaction: discord.Interaction,
        *,
        finished: bool = False,
    ) -> None:
        winners = [
            (state["user"], state["prize"])
            for state in self.btn_states
            if state["prize"] > 0 and state["claimed"]
        ]
        lines = []
        for idx, (user_id, prize) in enumerate(winners, start=1):
            display = f"<@{user_id}>" if user_id else "(미수령)"
            lines.append(f"{idx}. {display} — {prize:,}원")

        desc = "주간 복주머니! 25개 중 10개가 당첨입니다. 한 번만 참여 가능."
        if finished:
            desc += "\n🎊 모든 당첨자가 결정되었습니다!"

        embed = discord.Embed(
            title="🎁 주간 복주머니 이벤트",
            description=desc,
            color=0xF39C12,
            timestamp=datetime.now(SEOUL_TZ),
        )
        embed.add_field(
            name="당첨자 현황",
            value="\n".join(lines) if lines else "아직 없음",
            inline=False,
        )
        embed.set_footer(text="버튼을 눌러 복주머니를 열어보세요! (최대 1시간)")

        if self.original_message:
            try:
                await self.original_message.edit(embed=embed, view=self)
            except Exception:
                pass
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                try:
                    index = int(child.custom_id.split("_")[1])
                except Exception:
                    index = None
                if index is not None and self.btn_states[index]["prize"] > 0:
                    child.label = "기간만료"
                    child.style = discord.ButtonStyle.secondary
        if self.original_message:
            try:
                await self.original_message.edit(view=self)
            except Exception:
                pass


def create_lottery_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎁 주간 복주머니 이벤트",
        description="주간 복주머니! 25개 중 10개가 당첨입니다. 한 번만 참여 가능.",
        color=0xF39C12,
        timestamp=datetime.now(SEOUL_TZ),
    )
    embed.add_field(name="당첨자 현황", value="아직 없음", inline=False)
    embed.set_footer(text="버튼을 눌러 복주머니를 열어보세요! (최대 1시간)")
    return embed


def generate_prize_map() -> List[int]:
    prizes = [random.randint(10, 30) * 1000 for _ in range(10)]
    prize_map = [0] * 25
    for idx, prize in zip(random.sample(range(25), 10), prizes):
        prize_map[idx] = prize
    return prize_map


async def start_daily_lottery(
    channel: discord.abc.Messageable,
    guild_id: str,
    balance: BalanceService,
) -> None:
    timeout = 3600
    prize_map = generate_prize_map()
    view = WeeklyLotteryView(
        balance=balance,
        prize_map=prize_map,
        guild_id=guild_id,
        timeout=timeout,
    )
    embed = create_lottery_embed()
    message = await channel.send(embed=embed, view=view)
    view.original_message = message


__all__ = [
    "WeeklyLotteryView",
    "start_daily_lottery",
    "generate_prize_map",
    "create_lottery_embed",
]
