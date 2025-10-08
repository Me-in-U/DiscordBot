import json
import os
import random
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

# 서울 시간대 설정 (UTC+9)
SEOUL_TZ = timezone(timedelta(hours=9))
BALANCE_FILE = "gambling_balance.json"
FINAL_BALANCE_LABEL = "최종 잔액"


class GamblingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("Gambling Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> Gambling Cog : on ready!")

    def load_balance_data(self):
        """길드별 유저 잔액 데이터 로드"""
        if not os.path.isfile(BALANCE_FILE):
            return {}
        with open(BALANCE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_balance_data(self, data):
        """길드별 유저 잔액 데이터 저장"""
        with open(BALANCE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_user_balance(self, guild_id: str, user_id: str) -> int:
        """특정 유저의 잔액 조회"""
        data = self.load_balance_data()
        return data.get(guild_id, {}).get(user_id, {}).get("balance", 0)

    def set_user_balance(self, guild_id: str, user_id: str, amount: int):
        """특정 유저의 잔액 설정"""
        data = self.load_balance_data()
        if guild_id not in data:
            data[guild_id] = {}
        if user_id not in data[guild_id]:
            data[guild_id][user_id] = {"balance": 0, "last_daily": None}
        data[guild_id][user_id]["balance"] = amount
        self.save_balance_data(data)

    def get_last_daily(self, guild_id: str, user_id: str) -> str:
        """마지막 /돈줘 사용 일자 조회"""
        data = self.load_balance_data()
        return data.get(guild_id, {}).get(user_id, {}).get("last_daily")

    def set_last_daily(self, guild_id: str, user_id: str, date_str: str):
        """마지막 /돈줘 사용 일자 설정"""
        data = self.load_balance_data()
        if guild_id not in data:
            data[guild_id] = {}
        if user_id not in data[guild_id]:
            data[guild_id][user_id] = {"balance": 0, "last_daily": None}
        data[guild_id][user_id]["last_daily"] = date_str
        self.save_balance_data(data)

    def can_use_daily(self, guild_id: str, user_id: str) -> bool:
        """오늘 /돈줘를 사용할 수 있는지 확인"""
        last_daily = self.get_last_daily(guild_id, user_id)
        if last_daily is None:
            return True

        # 서울 시간대 기준으로 오늘 날짜 확인
        today = datetime.now(SEOUL_TZ).date().isoformat()
        return last_daily != today

    def get_guild_balances(self, guild_id: str) -> dict:
        """길드의 전체 유저 잔액 정보를 반환"""
        data = self.load_balance_data()
        return data.get(guild_id, {})

    @app_commands.command(
        name="돈줘", description="매일 1번 10,000원을 받을 수 있습니다."
    )
    async def daily_money(self, interaction: discord.Interaction):
        """매일 1번 10,000원 지급"""
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        if not self.can_use_daily(guild_id, user_id):
            await interaction.response.send_message(
                "❌ 오늘은 이미 돈을 받았습니다. 내일 다시 시도해주세요!",
                ephemeral=True,
            )
            return

        current_balance = self.get_user_balance(guild_id, user_id)
        new_balance = current_balance + 10000
        self.set_user_balance(guild_id, user_id, new_balance)

        today = datetime.now(SEOUL_TZ).date().isoformat()
        self.set_last_daily(guild_id, user_id, today)

        embed = discord.Embed(
            title="💰 일일 보상",
            description=f"{interaction.user.mention}님이 10,000원을 받았습니다!",
            color=0x00FF00,
        )
        embed.add_field(name="현재 잔액", value=f"{new_balance:,}원", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="잔액", description="보유한 돈을 확인합니다.")
    async def check_balance(self, interaction: discord.Interaction):
        """현재 잔액 확인"""
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        balance = self.get_user_balance(guild_id, user_id)

        embed = discord.Embed(
            title="💵 잔액 조회",
            description=f"{interaction.user.mention}님의 현재 잔액",
            color=0x3498DB,
        )
        embed.add_field(name="보유 금액", value=f"{balance:,}원", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="순위", description="현재 길드의 보유 금액 순위를 보여줍니다."
    )
    async def show_ranking(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ 길드 정보가 없습니다.", ephemeral=True
            )
            return

        balances = self.get_guild_balances(guild_id)
        if not balances:
            await interaction.response.send_message(
                "💤 아직 잔액 데이터가 없습니다. /돈줘 로 시작해보세요!", ephemeral=True
            )
            return

        # 잔액 기준 내림차순 정렬
        sorted_entries = sorted(
            balances.items(),
            key=lambda item: item[1].get("balance", 0),
            reverse=True,
        )

        max_entries = 10
        lines = []
        requester_rank = None
        requester_id = str(interaction.user.id)

        for idx, (user_id, info) in enumerate(sorted_entries, start=1):
            balance = info.get("balance", 0)
            member = guild.get_member(int(user_id)) if user_id.isdigit() else None
            display_name = member.display_name if member else f"<@{user_id}>"

            line = f"{idx}위 — {display_name}: {balance:,}원"
            if user_id == requester_id:
                requester_rank = idx
                line = f"**{line}**"
            lines.append(line)

        total_members = len(sorted_entries)
        description = "\n".join(lines[:max_entries])

        embed = discord.Embed(
            title="💎 길드 자산 순위",
            description=description,
            color=0x1ABC9C,
        )
        embed.set_footer(
            text=(
                f"총 {total_members}명 | 내 순위: {requester_rank}위"
                if requester_rank
                else f"총 {total_members}명 | 아직 순위에 없습니다."
            )
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="송금", description="다른 사용자에게 돈을 송금합니다.")
    @app_commands.rename(target_member="대상", amount="금액")
    @app_commands.describe(
        target_member="송금할 대상 유저를 선택하세요.",
        amount="송금할 금액을 입력하세요.",
    )
    async def transfer_money(
        self,
        interaction: discord.Interaction,
        target_member: discord.Member,
        amount: int,
    ):
        """다른 유저에게 송금"""
        guild_id = str(interaction.guild_id)
        sender_id = str(interaction.user.id)
        receiver_id = str(target_member.id)

        # 자신에게 송금 방지
        if sender_id == receiver_id:
            await interaction.response.send_message(
                "❌ 자신에게는 송금할 수 없습니다.", ephemeral=True
            )
            return

        # 봇에게 송금 방지
        if target_member.bot:
            await interaction.response.send_message(
                "❌ 봇에게는 송금할 수 없습니다.", ephemeral=True
            )
            return

        # 금액 유효성 검사
        if amount <= 0:
            await interaction.response.send_message(
                "❌ 송금 금액은 0보다 커야 합니다.", ephemeral=True
            )
            return

        # 잔액 확인
        sender_balance = self.get_user_balance(guild_id, sender_id)
        if sender_balance < amount:
            await interaction.response.send_message(
                f"❌ 잔액이 부족합니다. (현재 잔액: {sender_balance:,}원)",
                ephemeral=True,
            )
            return

        # 송금 처리
        new_sender_balance = sender_balance - amount
        receiver_balance = self.get_user_balance(guild_id, receiver_id)
        new_receiver_balance = receiver_balance + amount

        self.set_user_balance(guild_id, sender_id, new_sender_balance)
        self.set_user_balance(guild_id, receiver_id, new_receiver_balance)

        embed = discord.Embed(
            title="💸 송금 완료",
            description=f"{interaction.user.mention} → {target_member.mention}",
            color=0x9B59B6,
        )
        embed.add_field(name="송금 금액", value=f"{amount:,}원", inline=False)
        embed.add_field(
            name="보낸 사람 잔액", value=f"{new_sender_balance:,}원", inline=True
        )
        embed.add_field(
            name="받은 사람 잔액", value=f"{new_receiver_balance:,}원", inline=True
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="가위바위보",
        description="가위바위보 배팅 게임 (승리: 2배, 무승부: 절반, 패배: 전액 잃음)",
    )
    @app_commands.rename(choice="선택", bet_amount="배팅금액")
    @app_commands.describe(
        choice="가위, 바위, 보 중 하나를 선택하세요.",
        bet_amount="배팅할 금액을 입력하세요.",
    )
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
        """가위바위보 게임"""
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        # 배팅금액 유효성 검사
        if bet_amount <= 0:
            await interaction.response.send_message(
                "❌ 배팅 금액은 0보다 커야 합니다.", ephemeral=True
            )
            return

        # 잔액 확인
        current_balance = self.get_user_balance(guild_id, user_id)
        if current_balance < bet_amount:
            await interaction.response.send_message(
                f"❌ 잔액이 부족합니다. (현재 잔액: {current_balance:,}원)",
                ephemeral=True,
            )
            return

        # 배팅금액 차감
        new_balance = current_balance - bet_amount
        self.set_user_balance(guild_id, user_id, new_balance)

        # 봇의 선택
        choices = ["가위", "바위", "보"]
        bot_choice = random.choice(choices)
        user_choice = choice.value

        # 승부 판정
        result = ""
        prize = 0

        if user_choice == bot_choice:
            # 무승부
            result = "무승부"
            prize = bet_amount // 2
            color = 0xF39C12
        elif (
            (user_choice == "가위" and bot_choice == "보")
            or (user_choice == "바위" and bot_choice == "가위")
            or (user_choice == "보" and bot_choice == "바위")
        ):
            # 승리
            result = "승리"
            prize = bet_amount * 2
            color = 0x00FF00
        else:
            # 패배
            result = "패배"
            prize = 0
            color = 0xFF0000

        # 상금 지급
        final_balance = new_balance + prize
        self.set_user_balance(guild_id, user_id, final_balance)

        embed = discord.Embed(title="✊✋✌️ 가위바위보", color=color)
        embed.add_field(name="당신의 선택", value=user_choice, inline=True)
        embed.add_field(name="봇의 선택", value=bot_choice, inline=True)
        embed.add_field(name="결과", value=result, inline=False)
        embed.add_field(name="배팅 금액", value=f"{bet_amount:,}원", inline=True)
        embed.add_field(name="획득 금액", value=f"{prize:,}원", inline=True)
        embed.add_field(
            name=FINAL_BALANCE_LABEL, value=f"{final_balance:,}원", inline=False
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="도박", description="30%~70% 확률의 도박 (당첨: 2배, 실패: 전액 잃음)"
    )
    @app_commands.rename(bet_amount="배팅금액")
    @app_commands.describe(bet_amount="배팅할 금액을 입력하세요.")
    async def gamble(self, interaction: discord.Interaction, bet_amount: int):
        """랜덤 확률 도박"""
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        # 배팅금액 유효성 검사
        if bet_amount <= 0:
            await interaction.response.send_message(
                "❌ 배팅 금액은 0보다 커야 합니다.", ephemeral=True
            )
            return

        # 잔액 확인
        current_balance = self.get_user_balance(guild_id, user_id)
        if current_balance < bet_amount:
            await interaction.response.send_message(
                f"❌ 잔액이 부족합니다. (현재 잔액: {current_balance:,}원)",
                ephemeral=True,
            )
            return

        # 배팅금액 차감
        new_balance = current_balance - bet_amount
        self.set_user_balance(guild_id, user_id, new_balance)

        # 당첨 확률 결정 (30% ~ 70%)
        win_chance = random.randint(30, 70)
        roll = random.randint(1, 100)

        is_win = roll <= win_chance

        if is_win:
            # 당첨
            prize = bet_amount * 2
            final_balance = new_balance + prize
            result = "🎉 당첨!"
            color = 0x00FF00
        else:
            # 낙첨
            prize = 0
            final_balance = new_balance
            result = "💥 실패..."
            color = 0xFF0000

        self.set_user_balance(guild_id, user_id, final_balance)

        embed = discord.Embed(title="🎰 도박", description=result, color=color)
        embed.add_field(name="당첨 확률", value=f"{win_chance}%", inline=True)
        embed.add_field(name="결과 값", value=f"{roll}/100", inline=True)
        embed.add_field(name="배팅 금액", value=f"{bet_amount:,}원", inline=True)
        embed.add_field(name="획득 금액", value=f"{prize:,}원", inline=True)
        embed.add_field(
            name=FINAL_BALANCE_LABEL, value=f"{final_balance:,}원", inline=False
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="즉석복권", description="즉석복권 구매 (300원)")
    async def instant_lottery(self, interaction: discord.Interaction):
        """즉석복권"""
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        ticket_price = 300

        # 잔액 확인
        current_balance = self.get_user_balance(guild_id, user_id)
        if current_balance < ticket_price:
            await interaction.response.send_message(
                f"❌ 잔액이 부족합니다. (현재 잔액: {current_balance:,}원, 필요 금액: {ticket_price}원)",
                ephemeral=True,
            )
            return

        # 복권 구매 (차감)
        new_balance = current_balance - ticket_price
        self.set_user_balance(guild_id, user_id, new_balance)

        # 당첨 확률 및 금액 설정
        # 만원: 1%, 삼천원: 1.7%, 천원: 5.6%, 삼백원: 11.7%, 꽝: 나머지
        roll = random.uniform(0, 100)

        if roll < 1.0:
            # 만원 당첨
            prize = 10000
            result = "🎊 대박! 만원 당첨!"
            color = 0xFFD700
        elif roll < 2.7:  # 1.0 + 1.7
            # 삼천원 당첨
            prize = 3000
            result = "🎉 삼천원 당첨!"
            color = 0xC0C0C0
        elif roll < 8.3:  # 2.7 + 5.6
            # 천원 당첨
            prize = 1000
            result = "🎈 천원 당첨!"
            color = 0xCD7F32
        elif roll < 20.0:  # 8.3 + 11.7
            # 삼백원 당첨 (본전)
            prize = 300
            result = "😊 삼백원 당첨! (본전)"
            color = 0x3498DB
        else:
            # 꽝
            prize = 0
            result = "😢 꽝..."
            color = 0x95A5A6

        # 상금 지급
        final_balance = new_balance + prize
        self.set_user_balance(guild_id, user_id, final_balance)

        embed = discord.Embed(title="🎫 즉석복권", description=result, color=color)
        embed.add_field(name="구매 금액", value=f"{ticket_price}원", inline=True)
        embed.add_field(name="당첨 금액", value=f"{prize:,}원", inline=True)
        embed.add_field(
            name=FINAL_BALANCE_LABEL, value=f"{final_balance:,}원", inline=False
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(GamblingCommands(bot))
    print("Gambling Cog : setup 완료!")
