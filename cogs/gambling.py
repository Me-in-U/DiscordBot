import json
import os
import random
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

# 고정 상수
SEOUL_TZ = timezone(timedelta(hours=9))
BALANCE_FILE = "gambling_balance.json"
FINAL_BALANCE_LABEL = "최종 잔액"


class GamblingCommands(commands.Cog):
    """경제/미니게임 관련 명령어 Cog (정상화 및 footer 수정 버전)"""

    def __init__(self, bot):
        self.bot = bot
        print("Gambling Cog : init 로드 완료!")

    # ---------- 내부 유틸 ----------
    def _load_all(self) -> dict:
        if not os.path.isfile(BALANCE_FILE):
            return {}
        try:
            with open(BALANCE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_all(self, data: dict):
        with open(BALANCE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _ensure_user(self, data: dict, guild_id: str, user_id: str):
        if guild_id not in data:
            data[guild_id] = {}
        if user_id not in data[guild_id]:
            data[guild_id][user_id] = {"balance": 0, "last_daily": None}

    def get_user_balance(self, guild_id: str, user_id: str) -> int:
        data = self._load_all()
        return data.get(guild_id, {}).get(user_id, {}).get("balance", 0)

    def set_user_balance(self, guild_id: str, user_id: str, amount: int):
        data = self._load_all()
        self._ensure_user(data, guild_id, user_id)
        data[guild_id][user_id]["balance"] = amount
        self._save_all(data)

    def get_last_daily(self, guild_id: str, user_id: str):
        data = self._load_all()
        return data.get(guild_id, {}).get(user_id, {}).get("last_daily")

    def set_last_daily(self, guild_id: str, user_id: str, date_str: str):
        data = self._load_all()
        self._ensure_user(data, guild_id, user_id)
        data[guild_id][user_id]["last_daily"] = date_str
        self._save_all(data)

    def can_use_daily(self, guild_id: str, user_id: str) -> bool:
        last = self.get_last_daily(guild_id, user_id)
        if last is None:
            return True
        today = datetime.now(SEOUL_TZ).date().isoformat()
        return last != today

    def get_guild_balances(self, guild_id: str) -> dict:
        return self._load_all().get(guild_id, {})

    # ---------- 명령어 ----------
    @app_commands.command(
        name="돈줘", description="매일 1번 10,000원을 받을 수 있습니다."
    )
    async def daily_money(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        if not self.can_use_daily(guild_id, user_id):
            await interaction.response.send_message(
                "❌ 오늘은 이미 돈을 받았습니다. 내일 다시 시도해주세요!",
                ephemeral=True,
            )
            return

        current = self.get_user_balance(guild_id, user_id)
        final_balance = current + 10000
        self.set_user_balance(guild_id, user_id, final_balance)
        today = datetime.now(SEOUL_TZ).date().isoformat()
        self.set_last_daily(guild_id, user_id, today)

        embed = discord.Embed(
            title="💰 일일 보상",
            description=f"{interaction.user.mention}님이 10,000원을 받았습니다!",
            color=0x00AA00,
            timestamp=datetime.now(SEOUL_TZ),
        )
        embed.add_field(
            name=FINAL_BALANCE_LABEL, value=f"{final_balance:,}원", inline=False
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="잔액", description="현재 잔액을 확인합니다.")
    async def check_balance(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        bal = self.get_user_balance(guild_id, user_id)
        embed = discord.Embed(
            title="💵 잔액 조회",
            description=f"{interaction.user.mention}님의 잔액",
            color=0x3498DB,
        )
        embed.add_field(name="보유 금액", value=f"{bal:,}원", inline=False)
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

        sorted_entries = sorted(
            balances.items(), key=lambda kv: kv[1].get("balance", 0), reverse=True
        )
        requester_id = str(interaction.user.id)
        lines = []
        requester_rank = None
        for idx, (uid, info) in enumerate(sorted_entries, start=1):
            bal = info.get("balance", 0)
            member = guild.get_member(int(uid)) if uid.isdigit() else None
            name = member.display_name if member else f"<@{uid}>"
            line = f"{idx}위 — {name}: {bal:,}원"
            if uid == requester_id:
                requester_rank = idx
                line = f"**{line}**"
            lines.append(line)
        total = len(sorted_entries)
        embed = discord.Embed(
            title="💎 길드 자산 순위",
            description="\n".join(lines[:10]),
            color=0x1ABC9C,
        )
        footer = (
            f"총 {total}명 | 내 순위: {requester_rank}위"
            if requester_rank
            else f"총 {total}명 | 순위 정보 없음"
        )
        embed.set_footer(text=footer)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="송금", description="다른 사용자에게 돈을 송금합니다.")
    @app_commands.rename(target_member="대상", amount="금액")
    @app_commands.describe(target_member="송금 대상", amount="송금할 금액")
    async def transfer_money(
        self,
        interaction: discord.Interaction,
        target_member: discord.Member,
        amount: int,
    ):
        guild_id = str(interaction.guild_id)
        sender_id = str(interaction.user.id)
        receiver_id = str(target_member.id)

        if sender_id == receiver_id:
            await interaction.response.send_message(
                "❌ 자기 자신에게는 송금 불가", ephemeral=True
            )
            return
        if target_member.bot:
            await interaction.response.send_message(
                "❌ 봇에게는 송금 불가", ephemeral=True
            )
            return
        if amount <= 0:
            await interaction.response.send_message(
                "❌ 금액은 0보다 커야 합니다.", ephemeral=True
            )
            return

        sender_bal = self.get_user_balance(guild_id, sender_id)
        if sender_bal < amount:
            await interaction.response.send_message(
                f"❌ 잔액 부족 (현재 {sender_bal:,}원)", ephemeral=True
            )
            return

        receiver_bal = self.get_user_balance(guild_id, receiver_id)
        self.set_user_balance(guild_id, sender_id, sender_bal - amount)
        self.set_user_balance(guild_id, receiver_id, receiver_bal + amount)

        embed = discord.Embed(
            title="💸 송금 완료",
            description=f"{interaction.user.mention} → {target_member.mention}",
            color=0x9B59B6,
        )
        embed.add_field(name="송금 금액", value=f"{amount:,}원", inline=False)
        embed.add_field(
            name="보낸 사람 잔액", value=f"{sender_bal - amount:,}원", inline=True
        )
        embed.add_field(
            name="받은 사람 잔액", value=f"{receiver_bal + amount:,}원", inline=True
        )
        await interaction.response.send_message(embed=embed)

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
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        if bet_amount <= 0:
            await interaction.response.send_message(
                "❌ 배팅 금액은 0보다 커야 합니다.", ephemeral=True
            )
            return
        bal = self.get_user_balance(guild_id, user_id)
        if bal < bet_amount:
            await interaction.response.send_message(
                f"❌ 잔액 부족 (현재 {bal:,}원)", ephemeral=True
            )
            return
        bal_after_bet = bal - bet_amount
        self.set_user_balance(guild_id, user_id, bal_after_bet)

        bot_choice = random.choice(["가위", "바위", "보"])
        user_choice = choice.value
        if user_choice == bot_choice:
            result = "무승부"
            prize = bet_amount // 2
            color = 0xF1C40F
        elif (user_choice, bot_choice) in [
            ("가위", "보"),
            ("바위", "가위"),
            ("보", "바위"),
        ]:
            result = "승리"
            prize = bet_amount * 2
            color = 0x2ECC71
        else:
            result = "패배"
            prize = 0
            color = 0xE74C3C
        final_bal = bal_after_bet + prize
        self.set_user_balance(guild_id, user_id, final_bal)
        embed = discord.Embed(title="✊✋✌️ 가위바위보", color=color)
        embed.add_field(name="당신", value=user_choice, inline=True)
        embed.add_field(name="봇", value=bot_choice, inline=True)
        embed.add_field(name="결과", value=result, inline=False)
        embed.add_field(name="배팅", value=f"{bet_amount:,}원", inline=True)
        embed.add_field(name="획득", value=f"{prize:,}원", inline=True)
        embed.add_field(
            name=FINAL_BALANCE_LABEL, value=f"{final_bal:,}원", inline=False
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="도박", description="30~70% 확률 (성공 2배 / 실패 손실)")
    @app_commands.rename(bet_amount="배팅금액")
    @app_commands.describe(bet_amount="배팅할 금액")
    async def gamble(self, interaction: discord.Interaction, bet_amount: int):
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        if bet_amount <= 0:
            await interaction.response.send_message(
                "❌ 배팅 금액은 0보다 커야 합니다.", ephemeral=True
            )
            return
        bal = self.get_user_balance(guild_id, user_id)
        if bal < bet_amount:
            await interaction.response.send_message(
                f"❌ 잔액 부족 (현재 {bal:,}원)", ephemeral=True
            )
            return
        bal_after_bet = bal - bet_amount
        self.set_user_balance(guild_id, user_id, bal_after_bet)

        win_chance = random.randint(30, 70)
        roll = random.randint(1, 100)
        is_win = roll <= win_chance
        if is_win:
            prize = bet_amount * 2
            result_text = "🎉 당첨!"
            color = 0x2ECC71
        else:
            prize = 0
            result_text = "💥 실패..."
            color = 0xE74C3C
        final_bal = bal_after_bet + prize
        self.set_user_balance(guild_id, user_id, final_bal)

        embed = discord.Embed(
            title="🎰 도박 결과",
            description=result_text,
            color=color,
            timestamp=datetime.now(SEOUL_TZ),
        )
        embed.add_field(name="당첨 확률", value=f"{win_chance}%", inline=True)
        embed.add_field(name="추첨 값", value=f"{roll}/100", inline=True)
        footer_text = f"배팅 {bet_amount:,}원 • 획득 {prize:,}원 • 잔액 {final_bal:,}원"
        avatar_url = (
            interaction.user.display_avatar.url
            if interaction.user.display_avatar
            else None
        )
        if avatar_url:
            embed.set_footer(text=footer_text, icon_url=avatar_url)
        else:
            embed.set_footer(text=footer_text)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="즉석복권", description="300원 구매 / 확률형 보상")
    async def instant_lottery(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        ticket_price = 300
        bal = self.get_user_balance(guild_id, user_id)
        if bal < ticket_price:
            await interaction.response.send_message(
                f"❌ 잔액 부족 (현재 {bal:,}원 / 필요 {ticket_price}원)", ephemeral=True
            )
            return
        bal_after_buy = bal - ticket_price
        self.set_user_balance(guild_id, user_id, bal_after_buy)
        roll = random.uniform(0, 100)
        if roll < 1.0:
            prize, result_text, color = 10000, "🎊 1만원 당첨!", 0xFFD700
        elif roll < 2.7:
            prize, result_text, color = 3000, "🎉 3천원 당첨!", 0xC0C0C0
        elif roll < 8.3:
            prize, result_text, color = 1000, "🎈 1천원 당첨!", 0xCD7F32
        elif roll < 20.0:
            prize, result_text, color = 300, "😊 300원 (본전)", 0x3498DB
        else:
            prize, result_text, color = 0, "😢 꽝...", 0x95A5A6
        final_bal = bal_after_buy + prize
        self.set_user_balance(guild_id, user_id, final_bal)
        embed = discord.Embed(title="🎫 즉석복권", description=result_text, color=color)
        embed.add_field(name="구매", value=f"{ticket_price}원", inline=True)
        embed.add_field(name="당첨", value=f"{prize:,}원", inline=True)
        embed.add_field(
            name=FINAL_BALANCE_LABEL, value=f"{final_bal:,}원", inline=False
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(GamblingCommands(bot))
    print("Gambling Cog : setup 완료!")
