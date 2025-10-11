from __future__ import annotations

import asyncio
import random
from typing import List, Tuple

import discord

from .constants import BET_AMOUNT_REQUIRED, SEOUL_TZ
from .services import BalanceService


async def run_ladder_game(
    interaction: discord.Interaction,
    balance: BalanceService,
    *,
    bet_amount: int,
    rows: int = 8,
    payout_multiplier: float = 2.7,
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

    rungs = generate_ladder(rows=rows)
    winner_bottom = random.randint(1, 3)

    view = LadderView(
        balance=balance,
        guild_id=guild_id,
        user_id=user_id,
        bet_amount=bet_amount,
        rungs=rungs,
        winner_bottom=winner_bottom,
        payout_multiplier=payout_multiplier,
        timeout=180,
    )

    art_masked = build_ladder_ascii(
        rungs,
        reveal_middle=False,
        winner_bottom=None,
        choice_top=None,
    )
    embed = discord.Embed(
        title="🪜 사다리 타기",
        description=(
            f"3개 사다리 중 1개만 당첨! 배팅: {bet_amount:,}원\n"
            "중간은 가려져 있으며, 선택 후 경로와 결과가 공개됩니다."
        ),
        color=0x95A5A6,
        timestamp=_now(),
    )
    embed.add_field(name="사다리", value=art_masked, inline=False)

    await interaction.response.send_message(embed=embed, view=view)


class LadderView(discord.ui.View):
    def __init__(
        self,
        *,
        balance: BalanceService,
        guild_id: str,
        user_id: str,
        bet_amount: int,
        rungs: List[Tuple[bool, bool]],
        winner_bottom: int,
        payout_multiplier: float,
        timeout: int,
    ) -> None:
        super().__init__(timeout=timeout)
        self._balance = balance
        self.guild_id = guild_id
        self.user_id = user_id
        self.bet_amount = bet_amount
        self.rungs = rungs
        self.winner_bottom = winner_bottom
        self.payout_multiplier = payout_multiplier
        self.lock = asyncio.Lock()
        self.finished = False

        self.add_item(self._make_button("사다리 1", 1))
        self.add_item(self._make_button("사다리 2", 2))
        self.add_item(self._make_button("사다리 3", 3))

    def _make_button(self, label: str, value: int) -> discord.ui.Button:
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)

        async def callback(interaction: discord.Interaction) -> None:
            await self._resolve(interaction, value)

        button.callback = callback
        return button

    async def _resolve(self, interaction: discord.Interaction, choice: int) -> None:
        async with self.lock:
            if self.finished:
                await interaction.response.send_message(
                    "이미 결과가 공개된 게임입니다.", ephemeral=True
                )
                return

            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message(
                    "❌ 이 게임은 요청자만 참여할 수 있습니다.",
                    ephemeral=True,
                )
                return

            current = self._balance.get_balance(self.guild_id, self.user_id)
            if current < self.bet_amount:
                await interaction.response.send_message(
                    "❌ 잔액이 부족합니다.", ephemeral=True
                )
                return

            self._balance.set_balance(
                self.guild_id, self.user_id, current - self.bet_amount
            )

            end_col, path_positions = trace_ladder_path(choice, self.rungs)
            is_win = end_col == self.winner_bottom
            prize = int(self.bet_amount * self.payout_multiplier) if is_win else 0
            after_bet = self._balance.get_balance(self.guild_id, self.user_id)
            final_balance = after_bet + prize
            if prize:
                self._balance.set_balance(self.guild_id, self.user_id, final_balance)

            art = build_ladder_ascii(
                self.rungs,
                reveal_middle=True,
                highlight_path=path_positions,
                winner_bottom=self.winner_bottom,
                choice_top=choice,
            )

            title = "🪜 사다리 결과"
            desc = (
                "🎉 당첨!" if is_win else "😢 꽝..."
            ) + f"  선택:{choice} → 도착:{end_col}"
            color = 0x2ECC71 if is_win else 0xE74C3C
            embed = discord.Embed(
                title=title,
                description=desc,
                color=color,
                timestamp=_now(),
            )
            embed.add_field(name="사다리", value=art, inline=False)
            footer = f"배팅 {self.bet_amount:,}원 • 획득 {prize:,}원 • 잔액 {final_balance:,}원"
            avatar_url = (
                interaction.user.display_avatar.url
                if interaction.user.display_avatar
                else None
            )
            if avatar_url:
                embed.set_footer(text=footer, icon_url=avatar_url)
            else:
                embed.set_footer(text=footer)

            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            self.finished = True
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except Exception:
                pass

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True


def generate_ladder(rows: int = 8) -> List[Tuple[bool, bool]]:
    result: List[Tuple[bool, bool]] = []
    for _ in range(rows):
        r = random.random()
        if r < 0.25:
            result.append((True, False))
        elif r < 0.5:
            result.append((False, True))
        elif r < 0.55:
            result.append((False, False))
        else:
            result.append((False, False))
    return result


def trace_ladder_path(
    start_col: int, rungs: List[Tuple[bool, bool]]
) -> Tuple[int, List[int]]:
    pos = start_col
    positions: List[int] = []
    for r12, r23 in rungs:
        positions.append(pos)
        if r12 and pos in (1, 2):
            pos = 3 - pos
        elif r23 and pos in (2, 3):
            pos = 5 - pos
    return pos, positions


def build_ladder_ascii(
    rungs: List[Tuple[bool, bool]],
    *,
    reveal_middle: bool,
    highlight_path: List[int] | None = None,
    winner_bottom: int | None,
    choice_top: int | None,
) -> str:
    gap = 13
    col_x = [0, gap, gap * 2]
    width = gap * 2 + 1

    lines: List[str] = [_top_line(col_x, width)]

    if choice_top:
        lines.append(_choice_line(choice_top, col_x, width))

    for idx, rung in enumerate(rungs):
        path_pos = (
            highlight_path[idx]
            if highlight_path is not None and idx < len(highlight_path)
            else None
        )
        lines.append(
            _build_row(
                rung,
                reveal_middle=reveal_middle,
                path_pos=path_pos,
                col_positions=col_x,
                width=width,
            )
        )

    lines.append(_bottom_line(winner_bottom, col_x, width))

    return "``\n" + "\n".join(lines) + "\n``"


def _top_line(col_positions: List[int], width: int) -> str:
    chars = [" "] * width
    for index, col in enumerate(col_positions, start=1):
        chars[col] = str(index)
    return "".join(chars)


def _choice_line(choice_top: int, col_positions: List[int], width: int) -> str:
    chars = [" "] * width
    cx = col_positions[choice_top - 1]
    chars[cx] = "▲"
    return "".join(chars)


def _build_row(
    rung: Tuple[bool, bool],
    *,
    reveal_middle: bool,
    path_pos: int | None,
    col_positions: List[int],
    width: int,
) -> str:
    row = [" "] * width
    for col in col_positions:
        row[col] = "|"

    if path_pos:
        row[col_positions[path_pos - 1]] = "◆"

    if reveal_middle:
        _draw_middle_connections(row, rung, path_pos, col_positions)
    else:
        _mask_middle(row, col_positions)

    return "".join(row)


def _draw_middle_connections(
    row: List[str],
    rung: Tuple[bool, bool],
    path_pos: int | None,
    col_positions: List[int],
) -> None:
    r12, r23 = rung
    if r12:
        _fill_segment(
            row,
            start=col_positions[0] + 1,
            end=col_positions[1],
            char="◆" if path_pos in (1, 2) else "-",
        )
        if path_pos in (1, 2):
            destination = col_positions[(3 - path_pos) - 1]
            row[destination] = "◆"
    if r23:
        _fill_segment(
            row,
            start=col_positions[1] + 1,
            end=col_positions[2],
            char="◆" if path_pos in (2, 3) else "-",
        )
        if path_pos in (2, 3):
            destination = col_positions[(5 - path_pos) - 1]
            row[destination] = "◆"


def _fill_segment(row: List[str], *, start: int, end: int, char: str) -> None:
    for index in range(start, end):
        row[index] = char


def _mask_middle(row: List[str], col_positions: List[int]) -> None:
    for index in range(col_positions[0] + 1, col_positions[2]):
        if row[index] == " ":
            row[index] = "▒"


def _bottom_line(
    winner_bottom: int | None, col_positions: List[int], width: int
) -> str:
    chars = [" "] * width
    for index, col in enumerate(col_positions, start=1):
        if winner_bottom and index == winner_bottom:
            _write_label(chars, col, "WIN")
        elif 0 <= col < width:
            chars[col] = "·"
    return "".join(chars)


def _write_label(target: List[str], center: int, label: str) -> None:
    start = min(max(center - 1, 0), len(target) - len(label))
    for offset, char in enumerate(label):
        target[start + offset] = char


def _now():
    from datetime import datetime

    return datetime.now(SEOUL_TZ)


__all__ = [
    "run_ladder_game",
    "generate_ladder",
    "trace_ladder_path",
    "build_ladder_ascii",
]
