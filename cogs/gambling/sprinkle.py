from __future__ import annotations

import asyncio
import logging
from typing import List

import discord

from datetime import datetime

from .constants import SEOUL_TZ
from .services import BalanceService


logger = logging.getLogger(__name__)


class SprinkleView(discord.ui.View):
    """랜덤 금액 배분 뷰."""

    def __init__(
        self,
        *,
        balance: BalanceService,
        parts_list: List[int],
        sender_user: discord.User,
        guild_id: str,
        timeout: int = 300,
    ):
        super().__init__(timeout=timeout)
        self._balance = balance
        self.parts: List[int] = list(parts_list)
        self.claimed_users: set[str] = set()
        self.sender = sender_user
        self.guild_id = guild_id
        self.lock = asyncio.Lock()
        self.original_message: discord.Message | None = None

    @discord.ui.button(label="받기", style=discord.ButtonStyle.success)
    async def claim_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        async with self.lock:
            user_id = str(interaction.user.id)

            if interaction.user.id == self.sender.id:
                await interaction.response.send_message(
                    "❌ 본인이 뿌린 금액은 받을 수 없습니다.", ephemeral=True
                )
                return

            if user_id in self.claimed_users:
                await interaction.response.send_message(
                    "❌ 이미 수령했습니다.", ephemeral=True
                )
                return

            if not self.parts:
                button.disabled = True
                button.label = "종료"
                await interaction.response.edit_message(view=self)
                await interaction.response.send_message(
                    "❌ 이미 모두 수령되었습니다.", ephemeral=True
                )
                return

            amount = self.parts.pop()
            self.claimed_users.add(user_id)

            current = self._balance.get_balance(self.guild_id, user_id)
            self._balance.set_balance(self.guild_id, user_id, current + amount)

            await interaction.response.send_message(
                f"✅ {interaction.user.mention} 님이 {amount:,}원을 수령했습니다!",
                ephemeral=False,
            )

            if not self.parts:
                button.disabled = True
                button.label = "종료"
                try:
                    if self.original_message:
                        await self.original_message.edit(view=self)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    logger.debug("뿌리기 종료 메시지 수정 실패", exc_info=True)
                self.stop()

    async def on_timeout(self) -> None:
        remaining = sum(self.parts)
        if remaining > 0:
            sender_bal = self._balance.get_balance(self.guild_id, str(self.sender.id))
            self._balance.set_balance(
                self.guild_id, str(self.sender.id), sender_bal + remaining
            )
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                child.label = "기간만료"
                child.style = discord.ButtonStyle.secondary
        if self.original_message:
            try:
                await self.original_message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.debug("뿌리기 만료 메시지 수정 실패", exc_info=True)


def build_sprinkle_embed(
    user: discord.User, total_amount: int, people: int
) -> discord.Embed:
    embed = discord.Embed(
        title="🧧 뿌리기",
        description=f"{user.mention} 님이 총 {total_amount:,}원을 {people}명에게 뿌립니다!",
        color=0xE67E22,
        timestamp=datetime.now(SEOUL_TZ),
    )
    embed.add_field(
        name="수령 방법", value="버튼을 눌러 선착순으로 수령하세요.", inline=False
    )
    embed.set_footer(text="남은 인원이 모두 수령하면 자동 종료됩니다. (최대 5분)")
    return embed
