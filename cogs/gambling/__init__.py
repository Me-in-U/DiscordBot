from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .balance_info import show_balance as show_user_balance
from .daily_reward import grant_daily_money
from .gamble import run_gamble
from .instant_lottery import run_instant_lottery
from .ladder import run_ladder_game
from .lottery import start_daily_lottery as run_lottery_event
from .ranking import show_ranking as show_guild_ranking
from .rps import run_rock_paper_scissors
from .services import balance_service
from .sprinkle_command import run_sprinkle
from .slot_machine import run_slot_machine
from .transfer import execute_transfer


class GamblingCommands(commands.Cog):
    """경제/미니게임 관련 명령어 Cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._balance = balance_service
        print("Gambling Cog : init 로드 완료!")

    # ---------- 내부 유틸 ----------
    @property
    def balance(self):
        return self._balance

    def get_user_balance(self, guild_id: str, user_id: str) -> int:
        return self.balance.get_balance(guild_id, user_id)

    def set_user_balance(self, guild_id: str, user_id: str, amount: int):
        self.balance.set_balance(guild_id, user_id, amount)

    def add_result(self, guild_id: str, user_id: str, is_win: bool):
        self.balance.add_result(guild_id, user_id, is_win)

    def get_stats(self, guild_id: str, user_id: str) -> tuple[int, int, float]:
        return self.balance.get_stats(guild_id, user_id)

    def get_last_daily(self, guild_id: str, user_id: str):
        return self.balance.get_last_daily(guild_id, user_id)

    def set_last_daily(self, guild_id: str, user_id: str, date_str: str):
        self.balance.set_last_daily(guild_id, user_id, date_str)

    def can_use_daily(self, guild_id: str, user_id: str) -> bool:
        return self.balance.can_use_daily(guild_id, user_id)

    def get_guild_balances(self, guild_id: str) -> dict:
        return self.balance.get_guild_balances(guild_id)

    # ---------- 자동 이벤트(프로그램 호출용) ----------
    async def start_daily_lottery(
        self, channel: discord.abc.Messageable, guild_id: str
    ):
        """주간 복주머니를 지정 채널에 게시합니다 (25 버튼, 10 당첨)."""
        await run_lottery_event(channel, guild_id, self.balance)

    # ---------- 명령어 ----------
    @app_commands.command(
        name="뿌리기",
        description="지정 금액을 지정 인원에게 랜덤하게 나눠드립니다 (선착순 버튼 수령).",
    )
    @app_commands.rename(total_amount="금액", people="인원")
    @app_commands.describe(total_amount="뿌릴 총 금액", people="수령할 인원 수")
    async def sprinkle(
        self,
        interaction: discord.Interaction,
        total_amount: int,
        people: int,
    ):
        await run_sprinkle(
            interaction,
            self.balance,
            total_amount=total_amount,
            people=people,
        )

    @app_commands.command(
        name="돈줘", description="매일 1번 10,000원을 받을 수 있습니다."
    )
    async def daily_money(self, interaction: discord.Interaction):
        await grant_daily_money(interaction, self.balance)

    @app_commands.command(name="잔액", description="현재 잔액을 확인합니다.")
    async def check_balance(self, interaction: discord.Interaction):
        await show_user_balance(interaction, self.balance)

    @app_commands.command(
        name="순위", description="현재 길드의 보유 금액 순위를 보여줍니다."
    )
    async def show_ranking(self, interaction: discord.Interaction):
        await show_guild_ranking(interaction, self.balance)

    @app_commands.command(name="송금", description="다른 사용자에게 돈을 송금합니다.")
    @app_commands.rename(target_member="대상", amount="금액")
    @app_commands.describe(target_member="송금 대상", amount="송금할 금액")
    async def transfer_money(
        self,
        interaction: discord.Interaction,
        target_member: discord.Member,
        amount: int,
    ):
        await execute_transfer(
            interaction,
            self.balance,
            target_member=target_member,
            amount=amount,
        )

    @app_commands.command(
        name="가위바위보", description="승리 2배 / 무승부 절반 / 패배 0"
    )
    @app_commands.rename(choice="선택", bet_amount="배팅금액")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="가위", value="가위"),
            app_commands.Choice(name="바위", value="바위"),
            app_commands.Choice(name="보", value="보"),
        ]
    )
    async def rock_paper_scissors(
        self,
        interaction: discord.Interaction,
        choice: app_commands.Choice[str],
        bet_amount: int,
    ):
        await run_rock_paper_scissors(
            interaction,
            self.balance,
            choice_value=choice.value,
            bet_amount=bet_amount,
        )

    @app_commands.command(name="도박", description="30~70% 확률 (성공 2배 / 실패 손실)")
    @app_commands.rename(bet_amount="배팅금액")
    @app_commands.describe(bet_amount="배팅할 금액")
    async def gamble(self, interaction: discord.Interaction, bet_amount: int):
        await run_gamble(interaction, self.balance, bet_amount=bet_amount)

    @app_commands.command(name="즉석복권", description="300원 구매 / 확률형 보상")
    async def instant_lottery(self, interaction: discord.Interaction):
        await run_instant_lottery(interaction, self.balance)

    # ---------- 명령어: 사다리 ----------
    @app_commands.command(
        name="사다리",
        description="3사다리 중 1개 당첨! 배팅액을 걸고 사다리를 타보세요.",
    )
    @app_commands.rename(bet_amount="배팅액")
    @app_commands.describe(bet_amount="배팅할 금액")
    async def ladder_game(self, interaction: discord.Interaction, bet_amount: int):
        await run_ladder_game(interaction, self.balance, bet_amount=bet_amount)

    @app_commands.command(
        name="슬롯",
        description="3개의 슬롯을 돌려 같은 그림이 나오면 배당을 받습니다.",
    )
    @app_commands.rename(bet_amount="배팅금액")
    @app_commands.describe(bet_amount="배팅할 금액")
    async def slot_machine(self, interaction: discord.Interaction, bet_amount: int):
        await run_slot_machine(interaction, self.balance, bet_amount=bet_amount)


async def setup(bot: commands.Bot):
    await bot.add_cog(GamblingCommands(bot))
    print("Gambling Cog : setup 완료!")


__all__ = ["GamblingCommands", "setup"]
