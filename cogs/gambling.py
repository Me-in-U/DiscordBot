import asyncio
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
            # 신규 필드 추가 시 여기에서 기본값 초기화
            data[guild_id][user_id] = {
                "balance": 0,
                "last_daily": None,
                "wins": 0,
                "losses": 0,
            }
        else:
            # 기존 사용자 (마이그레이션): 누락된 키만 보충
            u = data[guild_id][user_id]
            if "wins" not in u:
                u["wins"] = 0
            if "losses" not in u:
                u["losses"] = 0

    def get_user_balance(self, guild_id: str, user_id: str) -> int:
        data = self._load_all()
        return data.get(guild_id, {}).get(user_id, {}).get("balance", 0)

    def set_user_balance(self, guild_id: str, user_id: str, amount: int):
        data = self._load_all()
        self._ensure_user(data, guild_id, user_id)
        data[guild_id][user_id]["balance"] = amount
        self._save_all(data)

    def add_result(self, guild_id: str, user_id: str, is_win: bool):
        """도박 결과(승/패) 기록."""
        data = self._load_all()
        self._ensure_user(data, guild_id, user_id)
        key = "wins" if is_win else "losses"
        data[guild_id][user_id][key] = int(data[guild_id][user_id].get(key, 0)) + 1
        self._save_all(data)

    def get_stats(self, guild_id: str, user_id: str) -> tuple[int, int, float]:
        data = self._load_all()
        user = data.get(guild_id, {}).get(user_id, {})
        w = int(user.get("wins", 0) or 0)
        l = int(user.get("losses", 0) or 0)
        total = w + l
        rate = (w / total * 100) if total > 0 else 0.0
        return w, l, rate

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

    # ---------- 자동 이벤트(프로그램 호출용) ----------
    async def start_weekly_lottery(
        self, channel: discord.abc.Messageable, guild_id: str
    ):
        """주간 복주머니를 지정 채널에 게시합니다 (25 버튼, 5 당첨)."""
        # 당첨 금액 5개 생성 (중복 허용, 1천원 단위)
        prizes = [random.randint(10, 30) * 1000 for _ in range(5)]
        # 25개 중 5개만 당첨, 나머지는 꽝(0원)
        prize_map = [0] * 25
        win_indices = random.sample(range(25), 5)
        for idx, prize in zip(win_indices, prizes):
            prize_map[idx] = prize

        # 내부 View 정의(명령어와 동일 로직)
        class WeeklyLotteryView(discord.ui.View):
            def __init__(
                self,
                cog: "GamblingCommands",
                *,
                prize_map: list[int],
                guild_id: str,
                timeout: int = 3600,
            ):
                super().__init__(timeout=timeout)
                self.cog = cog
                self.prize_map = prize_map.copy()
                self.claimed: dict[int, tuple[int, int]] = {}
                self.btn_states: list[dict] = [
                    dict(claimed=False, user=None, prize=prize) for prize in prize_map
                ]
                self.guild_id = guild_id
                self.lock = asyncio.Lock()
                self.original_message: discord.Message | None = None

                for i in range(25):
                    self.add_item(self._make_button(i))

            def _make_button(self, idx: int):
                label = f"복주머니 {idx+1}"
                style = discord.ButtonStyle.primary
                custom_id = f"lottery_{idx}"
                btn = discord.ui.Button(label=label, style=style, custom_id=custom_id)

                async def callback(interaction: discord.Interaction):
                    async with self.lock:
                        user_id = interaction.user.id
                        # 한 유저 1회 제한
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
                        prize = self.btn_states[idx]["prize"]
                        self.btn_states[idx]["claimed"] = True
                        self.btn_states[idx]["user"] = user_id
                        self.claimed[user_id] = (idx, prize)
                        btn.disabled = True
                        if prize > 0:
                            btn.label = f"🎉 {prize:,}원!"
                            btn.style = discord.ButtonStyle.success
                            current = self.cog.get_user_balance(
                                self.guild_id, str(user_id)
                            )
                            self.cog.set_user_balance(
                                self.guild_id, str(user_id), current + prize
                            )
                        else:
                            btn.label = "꽝"
                            btn.style = discord.ButtonStyle.secondary

                        await self._update_embed(interaction)

                        # 5명 모두 당첨이면 종료
                        if (
                            sum(
                                1
                                for s in self.btn_states
                                if s["prize"] > 0 and s["claimed"]
                            )
                            >= 5
                        ):
                            for child in self.children:
                                if isinstance(child, discord.ui.Button):
                                    child.disabled = True
                            await self._update_embed(interaction, finished=True)
                            self.stop()

                btn.callback = callback
                return btn

            async def _update_embed(
                self, interaction: discord.Interaction, finished: bool = False
            ):
                winners = [
                    (s["user"], s["prize"])
                    for s in self.btn_states
                    if s["prize"] > 0 and s["claimed"]
                ]
                lines = []
                for idx, (uid, prize) in enumerate(winners, start=1):
                    name = f"<@{uid}>" if uid else "(미수령)"
                    lines.append(f"{idx}. {name} — {prize:,}원")
                desc = "주간 복주머니! 25개 중 5개가 당첨입니다. 한 번만 참여 가능."
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

            async def on_timeout(self):
                for child in self.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                        # 당첨 버튼은 기간만료 표시
                        try:
                            idx = int(child.custom_id.split("_")[1])
                            if self.btn_states[idx]["prize"] > 0:
                                child.label = "기간만료"
                                child.style = discord.ButtonStyle.secondary
                        except Exception:
                            pass
                if self.original_message:
                    try:
                        await self.original_message.edit(view=self)
                    except Exception:
                        pass

        # 초기 임베드 + View 송출
        embed = discord.Embed(
            title="🎁 주간 복주머니 이벤트",
            description="주간 복주머니! 25개 중 5개가 당첨입니다. 한 번만 참여 가능.",
            color=0xF39C12,
            timestamp=datetime.now(SEOUL_TZ),
        )
        embed.add_field(name="당첨자 현황", value="아직 없음", inline=False)
        embed.set_footer(text="버튼을 눌러 복주머니를 열어보세요! (최대 1시간)")

        view = WeeklyLotteryView(
            self, prize_map=prize_map, guild_id=guild_id, timeout=3600
        )
        msg = await channel.send(embed=embed, view=view)
        view.original_message = msg

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
        guild_id = str(interaction.guild_id)
        sender_id = str(interaction.user.id)

        # 검증
        if total_amount <= 0 or people <= 0:
            await interaction.response.send_message(
                "❌ 금액과 인원은 0보다 커야 합니다.", ephemeral=True
            )
            return
        # 사람 수가 금액보다 큰 경우 최소 1원 보장을 위해 제한
        if people > total_amount:
            await interaction.response.send_message(
                f"❌ 인원({people})이 금액({total_amount})보다 많습니다. 최소 1원씩 지급하려면 인원을 줄여주세요.",
                ephemeral=True,
            )
            return
        # 송금자 잔액 확인
        sender_bal = self.get_user_balance(guild_id, sender_id)
        if sender_bal < total_amount:
            await interaction.response.send_message(
                f"❌ 잔액 부족 (현재 {sender_bal:,}원)", ephemeral=True
            )
            return

        # 미리 선차감
        self.set_user_balance(guild_id, sender_id, sender_bal - total_amount)

        # 랜덤 분할 (정수, 총합 = total_amount, 각 파트 >= 1)
        # 방법: 1..total_amount-1 범위에서 (people-1)개의 컷 포인트를 뽑아 차이로 분할
        cuts = (
            sorted(random.sample(range(1, total_amount), people - 1))
            if people > 1
            else []
        )
        parts = []
        prev = 0
        for c in cuts + [total_amount]:
            parts.append(c - prev)
            prev = c
        random.shuffle(parts)  # 버튼 수령 시 금액이 고정된 순서로 보이지 않게 섞기

        class SprinkleView(discord.ui.View):
            def __init__(
                self,
                cog: "GamblingCommands",
                *,
                parts_list: list[int],
                sender_user: discord.User,
                guild_id_str: str,
                timeout: int = 300,
            ):
                super().__init__(timeout=timeout)
                self.cog = cog
                self.parts: list[int] = parts_list  # 미지급 금액들
                self.claimed_users: set[str] = set()
                self.sender = sender_user
                self.guild_id = guild_id_str
                self.lock = asyncio.Lock()
                self.original_message: discord.Message | None = None

            @discord.ui.button(label="받기", style=discord.ButtonStyle.success)
            async def claim_button(
                self, interaction: discord.Interaction, button: discord.ui.Button
            ):
                async with self.lock:
                    user_id = str(interaction.user.id)

                    # 송금자는 수령 불가 (원하시면 허용 가능)
                    if interaction.user.id == self.sender.id:
                        await interaction.response.send_message(
                            "❌ 본인이 뿌린 금액은 받을 수 없습니다.", ephemeral=True
                        )
                        return

                    # 이미 수령했는지 체크
                    if user_id in self.claimed_users:
                        await interaction.response.send_message(
                            "❌ 이미 수령했습니다.", ephemeral=True
                        )
                        return

                    # 남은 파트가 없으면 비활성화
                    if not self.parts:
                        button.disabled = True
                        button.label = "종료"
                        await interaction.response.edit_message(view=self)
                        await interaction.response.send_message(
                            "❌ 이미 모두 수령되었습니다.", ephemeral=True
                        )
                        return

                    # 한 파트 지급
                    amount = self.parts.pop()
                    self.claimed_users.add(user_id)
                    # 사용자 잔액 증가
                    current = self.cog.get_user_balance(self.guild_id, user_id)
                    self.cog.set_user_balance(self.guild_id, user_id, current + amount)

                    # 안내 (개인 메시지)
                    await interaction.response.send_message(
                        f"✅ {amount:,}원을 수령했습니다!", ephemeral=True
                    )

                    # 남은 파트 없으면 버튼 비활성화
                    if not self.parts:
                        button.disabled = True
                        button.label = "종료"
                        try:
                            if self.original_message:
                                await self.original_message.edit(view=self)
                        except Exception:
                            pass
                        self.stop()

            async def on_timeout(self):
                # 타임아웃 시 남은 금액 환불
                remaining = sum(self.parts)
                if remaining > 0:
                    # 송금자에게 환불
                    sender_bal2 = self.cog.get_user_balance(
                        self.guild_id, str(self.sender.id)
                    )
                    self.cog.set_user_balance(
                        self.guild_id, str(self.sender.id), sender_bal2 + remaining
                    )
                # 버튼 비활성화 및 안내 문구 편집
                for child in self.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                        child.label = "기간만료"
                        child.style = discord.ButtonStyle.secondary
                if self.original_message:
                    try:
                        await self.original_message.edit(view=self)
                    except Exception:
                        pass

        # 임베드 생성 및 뷰 표시
        embed = discord.Embed(
            title="🧧 뿌리기",
            description=f"{interaction.user.mention} 님이 총 {total_amount:,}원을 {people}명에게 뿌립니다!",
            color=0xE67E22,
            timestamp=datetime.now(SEOUL_TZ),
        )
        embed.add_field(
            name="수령 방법", value="버튼을 눌러 선착순으로 수령하세요.", inline=False
        )
        embed.set_footer(text="남은 인원이 모두 수령하면 자동 종료됩니다. (최대 5분)")

        view = SprinkleView(
            self,
            parts_list=parts,
            sender_user=interaction.user,
            guild_id_str=guild_id,
            timeout=300,
        )
        await interaction.response.send_message(embed=embed, view=view)
        try:
            sent = await interaction.original_response()
            view.original_message = sent
        except Exception:
            pass

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

        def build_roulette(chance: int, value: int, width: int = 30) -> str:
            if width < 10:
                width = 10
            step = 100 / width
            pointer_index = min(width - 1, int((value - 1) / step))
            win_last_index = int((chance - 1) / step)
            bar_chars = ["█" if i <= win_last_index else "░" for i in range(width)]
            bar_line = "".join(bar_chars)
            pointer_line = [" "] * width
            pointer_line[pointer_index] = "▲"
            pointer_line = "".join(pointer_line)
            return f"`{bar_line}`\n`{pointer_line}`\n"

        roulette_visual = build_roulette(win_chance, roll)
        is_win = roll <= win_chance
        if is_win:
            prize = bet_amount * 2
            result_text = "🎉 당첨!"
            color = 0x2ECC71
        else:
            prize = 0
            result_text = "💥 실패..."
            color = 0xE74C3C
        # 잔액/통계 반영 (정상 들여쓰기 복구)
        final_bal = bal_after_bet + prize
        self.set_user_balance(guild_id, user_id, final_bal)
        # 승/패 누적 반영
        self.add_result(guild_id, user_id, is_win)
        wins, losses, rate = self.get_stats(guild_id, user_id)

        embed = discord.Embed(
            title="🎰 도박 결과",
            description=result_text,
            color=color,
            timestamp=datetime.now(SEOUL_TZ),
        )
        embed.add_field(name="당첨 확률", value=f"{win_chance}%", inline=True)
        embed.add_field(name="룰렛", value=roulette_visual, inline=False)
        embed.add_field(
            name="전적",
            value=f"승 {wins} · 패 {losses} (승률 {rate:.1f}%)",
            inline=False,
        )
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
