from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple

import discord

from common.discord_ui import SafeView
from .constants import BET_AMOUNT_REQUIRED, SEOUL_TZ
from .services import BalanceService


SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

# Lint: common repeated literals
ASCII_BACK_FILL = "│░░░░░░░░░│"
EMPTY_HAND = "(empty)"


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"


def build_deck(num_decks: int = 1) -> List[Card]:
    deck = [
        Card(rank=r, suit=s) for _ in range(num_decks) for s in SUITS for r in RANKS
    ]
    random.shuffle(deck)
    return deck


def hand_values(cards: List[Card]) -> Tuple[int, bool, bool]:
    """
    Return (best_total, is_blackjack, is_soft)
    - Aces can be 1 or 11.
    - Blackjack only if exactly two cards: A + 10/J/Q/K
    - is_soft indicates at least one Ace counted as 11 in the best_total
    """
    values = []
    aces = 0
    for c in cards:
        if c.rank == "A":
            aces += 1
            values.append(11)
        elif c.rank in {"K", "Q", "J", "10"}:
            values.append(10)
        else:
            values.append(int(c.rank))

    total = sum(values)
    soft = aces > 0
    # Adjust Aces from 11 to 1 while busting
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    # After adjustment, if no Ace counted as 11, it's not soft
    if aces == 0:
        soft = False

    is_bj = False
    if len(cards) == 2:
        ranks = {cards[0].rank, cards[1].rank}
        if "A" in ranks and any(r in ranks for r in {"10", "J", "Q", "K"}):
            is_bj = True

    return total, is_bj, soft


def format_hand(cards: List[Card]) -> str:
    return " ".join(str(c) for c in cards)


def possible_totals(cards: List[Card]) -> List[int]:
    """Return sorted possible totals. Prefer all <=21; if none, return the minimum (bust value)."""
    if not cards:
        return [0]
    base = 0
    aces = 0
    for c in cards:
        if c.rank == "A":
            aces += 1
            base += 1  # count as 1 initially
        elif c.rank in {"K", "Q", "J", "10"}:
            base += 10
        else:
            base += int(c.rank)

    totals = [base + 10 * k for k in range(aces + 1)]
    valid = [t for t in totals if t <= 21]
    return sorted(valid) if valid else [min(totals)]


def totals_text(cards: List[Card]) -> str:
    totals = possible_totals(cards)
    if len(totals) == 1:
        val = totals[0]
        return f"{val} (버스트)" if val > 21 else str(val)
    return "/".join(str(v) for v in totals)


# ---------- ASCII 렌더링 유틸 ----------
def _card_ascii_lines(rank: str, suit: str) -> List[str]:
    # 고정 폭 카드(폭 11)로 정렬: 5줄 구성
    # rank는 '10'일 수 있으므로 좌우 정렬 주의
    rank_l = f"{rank:<2}"  # 왼쪽 표시용
    rank_r = f"{rank:>2}"  # 오른쪽 표시용
    return [
        "┌─────────┐",
        f"│{rank_l}       │",
        f"│    {suit}    │",
        f"│       {rank_r}│",
        "└─────────┘",
    ]


def _back_card_ascii_lines() -> List[str]:
    # 카드 뒷면 패턴
    return [
        "┌─────────┐",
        ASCII_BACK_FILL,
        ASCII_BACK_FILL,
        ASCII_BACK_FILL,
        "└─────────┘",
    ]


def _render_cards_ascii(cards: List[Card], *, hidden_index: int | None = None) -> str:
    if not cards:
        return EMPTY_HAND
    # 각 카드를 개별 라인 리스트로 만든 후, 같은 인덱스 라인끼리 가로로 이어붙임
    blocks: List[List[str]] = []
    for i, c in enumerate(cards):
        if hidden_index is not None and i == hidden_index:
            blocks.append(_back_card_ascii_lines())
        else:
            blocks.append(_card_ascii_lines(c.rank, c.suit))
    # 모든 카드 블록은 동일한 높이(5줄)
    lines_joined: List[str] = []
    for row in range(len(blocks[0])):
        parts = [blk[row] for blk in blocks]
        lines_joined.append(" ".join(parts))
    return "```\n" + "\n".join(lines_joined) + "\n```"


class BlackjackView(SafeView):
    def __init__(
        self,
        *,
        balance: BalanceService,
        guild_id: str,
        user_id: str,
        bet_amount: int,
        num_decks: int = 1,
    ) -> None:
        super().__init__(timeout=120)
        self._MSG_ALREADY_FINISHED = "이미 종료된 게임입니다."
        self._reshuffle_threshold = 10  # 이어하기 시 이 장수 미만이면 새 덱으로 재섞음
        self.balance = balance
        self.guild_id = guild_id
        self.user_id = user_id
        self.base_bet = bet_amount
        self.current_bet = bet_amount
        self.num_decks = num_decks

        self.deck: List[Card] = build_deck(num_decks)
        self.player: List[Card] = []
        self.dealer: List[Card] = []
        self.finished: bool = False
        self.can_double: bool = True
        self.message: discord.Message | None = None
        self.just_shuffled: bool = False  # 이어하기로 새 덱을 쓴 경우 안내용

        # 초기 베팅 차감 및 배분
        # self._reserve_bet(self.current_bet) -> start()에서 수행
        # self._initial_deal() -> start()에서 수행

    # ---------- 공용 유틸 ----------
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message(
                "이 블랙잭 게임은 명령을 실행한 사용자만 조작할 수 있습니다!",
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

    # ---------- 버튼들 ----------
    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.finished:
            await interaction.response.send_message(
                self._MSG_ALREADY_FINISHED, ephemeral=True
            )
            return
        self.can_double = False
        self.player.append(self._draw())

        player_total, _, _ = hand_values(self.player)
        if player_total > 21:  # 플레이어 버스트
            await self._finish(interaction)
            return
        await interaction.response.edit_message(
            embed=await self._build_embed(reveal_dealer=False), view=self
        )

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        if self.finished:
            await interaction.response.send_message(
                self._MSG_ALREADY_FINISHED, ephemeral=True
            )
            return
        self.can_double = False
        await self._dealer_play()
        await self._finish(interaction)

    @discord.ui.button(label="Double", style=discord.ButtonStyle.danger)
    async def double_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.finished:
            await interaction.response.send_message(
                self._MSG_ALREADY_FINISHED, ephemeral=True
            )
            return
        if not self.can_double:
            await interaction.response.send_message(
                "지금은 더블다운을 할 수 없습니다.", ephemeral=True
            )
            return
        # 추가 베팅 가능 여부 확인
        current = await self.balance.get_balance(self.guild_id, self.user_id)
        if current < self.base_bet:
            await interaction.response.send_message(
                "❌ 잔액이 부족하여 더블다운을 할 수 없습니다.", ephemeral=True
            )
            return
        # 추가 베팅 차감 및 한 장만 받고 바로 스탠드
        await self._reserve_bet(self.base_bet)
        self.current_bet += self.base_bet
        self.can_double = False
        self.player.append(self._draw())
        await self._dealer_play()
        await self._finish(interaction)

    @discord.ui.button(
        label="이어하기", style=discord.ButtonStyle.success, disabled=True
    )
    async def continue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.finished:
            await interaction.response.send_message(
                "아직 라운드가 끝나지 않았습니다.", ephemeral=True
            )
            return
        # 동일 배팅금액으로 남은 덱으로 새 라운드 시작
        current = await self.balance.get_balance(self.guild_id, self.user_id)
        if current < self.base_bet:
            await interaction.response.send_message(
                "❌ 잔액 부족으로 다시 시작할 수 없습니다.", ephemeral=True
            )
            return

        # 덱이 부족하면 새로 섞기
        if len(self.deck) < self._reshuffle_threshold:
            self.deck = build_deck(self.num_decks)
            self.just_shuffled = True
        else:
            self.just_shuffled = False

        # 상태 초기화 (덱 유지/보충)
        self.player.clear()
        self.dealer.clear()
        self.finished = False
        self.current_bet = self.base_bet
        self.can_double = True

        await self._reserve_bet(self.current_bet)
        self._initial_deal()

        # 버튼들 상태 복구
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.label == "이어하기":
                    child.disabled = True
                else:
                    child.disabled = False

        await interaction.response.edit_message(
            embed=await self._build_embed(reveal_dealer=False), view=self
        )

    # ---------- 내부 로직 ----------
    def _initial_deal(self) -> None:
        # 플레이어 2장, 딜러 2장 (딜러 한 장은 히든)
        self.player.append(self._draw())
        self.dealer.append(self._draw())
        self.player.append(self._draw())
        self.dealer.append(self._draw())

    async def start(self) -> None:
        await self._reserve_bet(self.current_bet)
        self._initial_deal()

    def _draw(self) -> Card:
        if not self.deck:
            self.deck = build_deck(self.num_decks)
        return self.deck.pop()

    async def _reserve_bet(self, amount: int) -> None:
        current = await self.balance.get_balance(self.guild_id, self.user_id)
        await self.balance.set_balance(self.guild_id, self.user_id, current - amount)

    async def _dealer_play(self) -> None:
        # 딜러는 17 이상이 되기 전까지 카드를 받는다 (Soft 17에서는 정지)
        while True:
            total, _, _ = hand_values(self.dealer)
            if total < 17:
                self.dealer.append(self._draw())
                continue
            # 17 이상이면 정지 (소프트 17 포함)
            break

    async def _finish(self, interaction: discord.Interaction) -> None:
        self.finished = True
        # 버튼 상태 정리: 이어하기만 활성화, 나머지 비활성화
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = child.label != "이어하기"

        # 결과 계산 및 정산
        player_total, player_bj, _ = hand_values(self.player)
        dealer_total, dealer_bj, _ = hand_values(self.dealer)
        prize, outcome, record = self._compute_payout(
            player_total=player_total,
            dealer_total=dealer_total,
            player_initial=(len(self.player) == 2),
            dealer_initial=(len(self.dealer) == 2),
            player_bj=player_bj,
            dealer_bj=dealer_bj,
        )
        # 승/패/무 기록 (블랙잭 전용)
        await self.balance.add_blackjack_result(self.guild_id, self.user_id, record)

        # 정산 반영
        current = await self.balance.get_balance(self.guild_id, self.user_id)
        await self.balance.set_balance(self.guild_id, self.user_id, current + prize)

        await interaction.response.edit_message(
            embed=await self._build_embed(
                reveal_dealer=True, final_outcome=outcome, prize=prize
            ),
            view=self,
        )

    def _compute_payout(
        self,
        *,
        player_total: int,
        dealer_total: int,
        player_initial: bool,
        dealer_initial: bool,
        player_bj: bool,
        dealer_bj: bool,
    ) -> tuple[int, str, str]:
        """계산된 상금(prize), 결과 텍스트(outcome), 기록 타입(win/lose/push) 반환."""
        # 플레이어 버스트 즉시 패배
        if player_total > 21:
            return 0, "패배", "lose"

        # 블랙잭 판정 (양측 초기 2장 상태에서만 유효)
        if player_initial and dealer_initial and (player_bj or dealer_bj):
            if player_bj and dealer_bj:
                return self.current_bet, "무승부", "push"
            if player_bj:
                return (self.current_bet * 5) // 2, "블랙잭 승리", "win"
            return 0, "딜러 블랙잭, 패배", "lose"

        # 일반 비교
        if dealer_total > 21:
            return self.current_bet * 2, "딜러 버스트, 승리", "win"
        if player_total > dealer_total:
            return self.current_bet * 2, "승리", "win"
        if player_total < dealer_total:
            return 0, "패배", "lose"
        return self.current_bet, "무승부", "push"

    async def _build_embed(
        self,
        *,
        reveal_dealer: bool,
        final_outcome: str | None = None,
        prize: int | None = None,
    ) -> discord.Embed:
        timestamp = datetime.now(SEOUL_TZ)
        title = "🃏 블랙잭"
        desc = self._description_for(final_outcome)
        color = self._color_for(final_outcome)

        embed = discord.Embed(
            title=title, description=desc, color=color, timestamp=timestamp
        )

        # 플레이어
        p_total, p_bj, _ = hand_values(self.player)
        p_hand_txt = (
            _render_cards_ascii(self.player) + f"\n합계: {totals_text(self.player)}"
        )
        if p_bj and len(self.player) == 2:
            p_title = f"플레이어 ({p_total}) — Blackjack"
        else:
            p_title = f"플레이어 ({p_total})"
        embed.add_field(name=p_title, value=p_hand_txt or EMPTY_HAND, inline=False)

        # 딜러
        d_title, d_hand_txt = self._dealer_field(reveal_dealer)
        if reveal_dealer and self.dealer:
            d_hand_txt = (
                _render_cards_ascii(self.dealer) + f"\n합계: {totals_text(self.dealer)}"
            )
        elif not reveal_dealer and self.dealer:
            # 업카드만 공개, 홀카드는 뒷면 처리
            d_hand_txt = _render_cards_ascii(self.dealer, hidden_index=1)
        embed.add_field(name=d_title, value=d_hand_txt, inline=False)

        # 잔액/배팅/배당 안내
        current = await self.balance.get_balance(self.guild_id, self.user_id)
        info_lines = [
            f"배팅: {self.current_bet:,}원",
            f"현재 잔액: {current:,}원",
            "배당: 일반 승리 1배, 블랙잭 1.5배 (총 2.5배 수령)",
            "더블다운: 초기 2장 상태에서 1장만 추가 후 자동 스탠드",
        ]
        # 덱 정보 및 안내
        info_lines.append(f"남은 카드: {len(self.deck)}장")
        if self.just_shuffled:
            info_lines.append("이번 판은 새 카드덱으로 시작했습니다.")
        elif len(self.deck) < self._reshuffle_threshold:
            info_lines.append("다음 이어하기 시 새 카드덱으로 재섞기 예정")
        if final_outcome is not None and prize is not None:
            net = prize - self.current_bet
            info_lines.append(f"이번 판 수령액: {prize:,}원 (순이익 {net:+,}원)")
            # 라운드 종료시에만 블랙잭 전용 전적을 보여준다
            bj_w, bj_l, bj_p, bj_rate = await self.balance.get_blackjack_stats(
                self.guild_id, self.user_id
            )
            info_lines.append(
                f"블랙잭 전적: 승 {bj_w} · 패 {bj_l} · 무 {bj_p} (승률 {bj_rate:.1f}%)"
            )
        embed.add_field(name="정보", value="\n".join(info_lines), inline=False)

        return embed

    def _description_for(self, final_outcome: str | None) -> str:
        if final_outcome is None:
            return "버튼으로 진행하세요. (Dealer는 17 이상에서 정지)"
        return f"결과: {final_outcome}"

    def _color_for(self, final_outcome: str | None) -> discord.Color:
        if final_outcome is None:
            return discord.Color.blurple()
        if "승" in final_outcome:
            return discord.Color.gold()
        if "무" in final_outcome:
            return discord.Color.orange()
        return discord.Color.red()

    def _dealer_field(self, reveal_dealer: bool) -> tuple[str, str]:
        if reveal_dealer:
            d_total, d_bj, _ = hand_values(self.dealer)
            d_title = f"딜러 ({d_total})" + (
                " — Blackjack" if d_bj and len(self.dealer) == 2 else ""
            )
            d_hand_txt = _render_cards_ascii(self.dealer) if self.dealer else EMPTY_HAND
        else:
            d_title = "딜러 ( ? )"
            d_hand_txt = (
                _render_cards_ascii(self.dealer, hidden_index=1)
                if self.dealer
                else EMPTY_HAND
            )
        return d_title, d_hand_txt


async def run_blackjack(
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
    current = await balance.get_balance(guild_id, user_id)
    if current < bet_amount:
        await interaction.response.send_message(
            f"❌ 잔액 부족 (현재 {current:,}원)", ephemeral=True
        )
        return

    view = BlackjackView(
        balance=balance,
        guild_id=guild_id,
        user_id=user_id,
        bet_amount=bet_amount,
        num_decks=1,
    )
    await view.start()

    await interaction.response.send_message(
        embed=await view._build_embed(reveal_dealer=False), view=view
    )
    view.message = await interaction.original_response()


__all__ = ["run_blackjack"]
