from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import discord

from common.discord_ui import SafeView
from .constants import BET_AMOUNT_REQUIRED, SEOUL_TZ
from .services import BalanceService


@dataclass(frozen=True)
class SlotSymbol:
    emoji: str
    weight: int
    multiplier: int


SYMBOLS: Sequence[SlotSymbol] = (
    SlotSymbol("🍒", 40, 5),
    SlotSymbol("🔔", 25, 15),
    SlotSymbol("🧩", 20, 30),
    SlotSymbol("♥️", 15, 50),
)

EMOJIS = [symbol.emoji for symbol in SYMBOLS]
WEIGHTS = [symbol.weight for symbol in SYMBOLS]
MULTIPLIER_MAP = {symbol.emoji: symbol.multiplier for symbol in SYMBOLS}
PROBABILITY_TABLE = "\n".join(
    f"{symbol.emoji * 3} → {symbol.multiplier}배 (개별 슬롯 {symbol.weight}%)"
    for symbol in SYMBOLS
)


class SlotMachineView(SafeView):
    def __init__(
        self,
        *,
        balance: BalanceService,
        guild_id: str,
        user_id: str,
        bet_amount: int,
    ) -> None:
        super().__init__(timeout=180)
        self.balance = balance
        self.guild_id = guild_id
        self.user_id = user_id
        self.bet_amount = bet_amount
        self.message: discord.Message | None = None
        self._busy: bool = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Compare as string to match stored self.user_id type
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "이 슬롯 머신은 명령을 실행한 사용자만 사용할 수 있습니다!",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="돌리기", style=discord.ButtonStyle.primary, emoji="🎰")
    async def spin_button(  # type: ignore[override]
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        # 중복 클릭/중첩 스핀 방지
        if self._busy:
            await interaction.response.send_message("⏳ 이전 스핀이 처리 중입니다...", ephemeral=True)
            return
        self._busy = True
        try:
            embed, _ = self._spin(interaction)
            # 버튼은 유지하여 같은 임베드에서 계속 플레이 가능
            if interaction.response.is_done():
                await interaction.followup.edit_message(message_id=self.message.id, embed=embed, view=self)  # type: ignore[arg-type]
            else:
                await interaction.response.edit_message(embed=embed, view=self)
            # 잔액 부족이어도 계속 같은 메시지에서 재도전 가능하게 둠
        finally:
            self._busy = False

    def _spin(self, interaction: discord.Interaction) -> tuple[discord.Embed, bool]:
        current = self.balance.get_balance(self.guild_id, self.user_id)
        if current < self.bet_amount:
            embed = _build_insufficient_embed(
                interaction=interaction,
                current_balance=current,
                bet_amount=self.bet_amount,
            )
            return embed, True

        spins = random.choices(EMOJIS, weights=WEIGHTS, k=3)
        is_win = all(symbol == spins[0] for symbol in spins)
        symbol = spins[0] if is_win else None
        multiplier = MULTIPLIER_MAP.get(symbol, 0) if symbol else 0
        prize = self.bet_amount * multiplier if is_win else 0
        final_balance = current - self.bet_amount + prize

        self.balance.set_balance(self.guild_id, self.user_id, final_balance)
        self.balance.add_result(self.guild_id, self.user_id, is_win)
        wins, losses, rate = self.balance.get_stats(self.guild_id, self.user_id)

        embed = _build_result_embed(
            interaction=interaction,
            spins=spins,
            is_win=is_win,
            multiplier=multiplier,
            prize=prize,
            bet_amount=self.bet_amount,
            final_balance=final_balance,
            wins=wins,
            losses=losses,
            rate=rate,
        )
        return embed, False


async def run_slot_machine(
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

    current = balance.get_balance(guild_id, user_id)
    if current < bet_amount:
        await interaction.response.send_message(
            f"❌ 잔액 부족 (현재 {current:,}원)", ephemeral=True
        )
        return

    view = SlotMachineView(
        balance=balance,
        guild_id=guild_id,
        user_id=user_id,
        bet_amount=bet_amount,
    )
    # 최초에는 결과를 바로 보여주지 않고 대기 화면을 출력
    initial_embed = _build_initial_embed(
        interaction=interaction,
        bet_amount=bet_amount,
        current_balance=current,
    )
    await interaction.response.send_message(embed=initial_embed, view=view)
    view.message = await interaction.original_response()


def _build_result_embed(
    *,
    interaction: discord.Interaction,
    spins: list[str],
    is_win: bool,
    multiplier: int,
    prize: int,
    bet_amount: int,
    final_balance: int,
    wins: int,
    losses: int,
    rate: float,
) -> discord.Embed:
    timestamp = interaction.created_at or datetime.now(SEOUL_TZ)

    if is_win:
        result_text = f"🎉 잭팟! {spins[0] * 3} {multiplier}배 당첨!"
        color = discord.Color.gold()
    else:
        result_text = "💣 아쉽게도 일치하는 슬롯이 없어요."
        color = discord.Color.red()

    embed = discord.Embed(
        title="🎰 슬롯 머신",
        description=result_text,
        color=color,
        timestamp=timestamp,
    )
    embed.add_field(
        name="🎡 슬롯 휠",
        value=_build_slot_ascii(spins, highlight=is_win),
        inline=False,
    )
    net = prize - bet_amount
    result_detail = [
        f"배팅: {bet_amount:,}원",
        f"획득: {prize:,}원",
        f"순이익: {net:+,}원",
        f"현재 잔액: {final_balance:,}원",
    ]
    if is_win:
        result_detail.append(f"배율: {multiplier}배")
    embed.add_field(
        name="결과 정보",
        value="\n".join(result_detail),
        inline=False,
    )
    embed.add_field(
        name="전적",
        value=f"승 {wins} · 패 {losses} (승률 {rate:.1f}%)",
        inline=True,
    )
    embed.add_field(name="배당표", value=PROBABILITY_TABLE, inline=True)

    avatar = interaction.user.display_avatar
    footer_text = "돌리기 버튼으로 다시 도전하세요!"
    if avatar:
        embed.set_footer(text=footer_text, icon_url=avatar.url)
    else:
        embed.set_footer(text=footer_text)
    return embed


def _build_initial_embed(
    *,
    interaction: discord.Interaction,
    bet_amount: int,
    current_balance: int,
) -> discord.Embed:
    """슬롯 최초 호출 시 보여줄 대기 화면 임베드."""
    timestamp = interaction.created_at or datetime.now(SEOUL_TZ)
    spins = ["❓", "❔", "❓"]
    embed = discord.Embed(
        title="🎰 슬롯 머신",
        description="버튼을 눌러 슬롯을 돌려보세요!",
        color=discord.Color.blurple(),
        timestamp=timestamp,
    )
    embed.add_field(
        name="🎡 슬롯 휠",
        value=_build_slot_ascii(spins, highlight=False),
        inline=False,
    )
    embed.add_field(
        name="배팅 정보",
        value=f"배팅: {bet_amount:,}원\n현재 잔액: {current_balance:,}원",
        inline=True,
    )
    embed.add_field(name="배당표", value=PROBABILITY_TABLE, inline=True)

    avatar = interaction.user.display_avatar
    footer_text = "돌리기 버튼을 눌러 플레이하세요!"
    if avatar:
        embed.set_footer(text=footer_text, icon_url=avatar.url)
    else:
        embed.set_footer(text=footer_text)
    return embed


def _build_insufficient_embed(
    *,
    interaction: discord.Interaction,
    current_balance: int,
    bet_amount: int,
) -> discord.Embed:
    timestamp = interaction.created_at or datetime.now(SEOUL_TZ)
    embed = discord.Embed(
        title="잔액 부족",
        description=(
            "💸 슬롯을 돌리기 위한 잔액이 부족합니다.\n"
            f"필요 금액: {bet_amount:,}원 · 보유 잔액: {current_balance:,}원"
        ),
        color=discord.Color.greyple(),
        timestamp=timestamp,
    )
    embed.add_field(name="배당표", value=PROBABILITY_TABLE, inline=False)
    embed.set_footer(text="돈을 모은 뒤 다시 도전해 보세요!")
    return embed


def _build_slot_ascii(spins: list[str], *, highlight: bool) -> str:
    top = "`┏━━━━━━┳━━━━━━┳━━━━━━┓`"
    middle = f"`┃  {spins[0]}  ┃  {spins[1]}  ┃  {spins[2]}  ┃`"
    bottom = "`┗━━━━━━┻━━━━━━┻━━━━━━┛`"
    pointer = "`   ⭐      ⭐      ⭐   `" if highlight else "`   ▲      ▲      ▲   `"
    return "\n".join([top, middle, bottom, pointer])


__all__ = ["run_slot_machine"]
