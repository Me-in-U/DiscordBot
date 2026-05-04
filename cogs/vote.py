from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

STATUS_RUNNING = "투표 진행 중"
STATUS_COMPLETED = "투표 완료"
STATUS_TIMEOUT = "시간 초과"
STATUS_FINISHED = "투표 종료"


class VoteButton(discord.ui.Button["VoteView"]):
    def __init__(self, view: "VoteView", label: str, index: int):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label[:80],  # Discord 버튼 라벨은 최대 80자
            custom_id=f"vote_option_{index}",
        )
        self.index = index
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):  # type: ignore[override]
        await self.view_ref.handle_vote(interaction, self.index)


class VoteView(discord.ui.View):
    def __init__(
        self,
        cog: "VoteCog",
        options: List[str],
        target_count: int,
        owner: discord.abc.User,
        timeout: Optional[float] = 3600.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.options = options
        self.target_count = target_count
        self.owner = owner
        self.votes: List[int] = [0 for _ in options]
        self.voters: Dict[int, int] = {}
        self.total_votes = 0
        self.finished = False
        self.lock = asyncio.Lock()
        self.message: Optional[discord.Message] = None
        self.status_text: str = STATUS_RUNNING

        for idx, option in enumerate(options):
            self.add_item(VoteButton(self, option, idx))

    async def on_timeout(self) -> None:
        if not self.finished:
            self.status_text = STATUS_TIMEOUT
            await self.finalize(send_followup=False)

    def _result_text(self) -> str:
        if self.total_votes == 0:
            return "투표 참여자가 없었습니다."
        max_vote = max(self.votes)
        if max_vote == 0:
            return "모든 항목이 0표입니다."
        winners = [opt for opt, cnt in zip(self.options, self.votes) if cnt == max_vote]
        if len(winners) == 1:
            return f"우승: **{winners[0]}** ({max_vote}표)"
        winners_text = ", ".join(f"**{w}**" for w in winners)
        return f"공동 우승: {winners_text} ({max_vote}표)"

    def build_embed(self) -> discord.Embed:
        title = "투표 결과" if self.finished else "투표 진행 중"
        embed = discord.Embed(title=title, color=discord.Color.blurple())

        lines = []
        for idx, option in enumerate(self.options):
            vote_count = self.votes[idx]
            lines.append(f"{idx + 1}. {option} — **{vote_count}표**")
        embed.description = "\n".join(lines)

        embed.add_field(
            name="진행 상황",
            value=f"{self.total_votes}/{self.target_count}명 참여",
            inline=False,
        )

        if self.finished:
            embed.add_field(name="결과", value=self._result_text(), inline=False)

        embed.set_footer(
            text=f"상태: {self.status_text} | 요청자: {self.owner.display_name}"
        )
        return embed

    async def bind_message(self, message: discord.Message) -> None:
        self.message = message
        await self.message.edit(embed=self.build_embed(), view=self)

    async def handle_vote(self, interaction: discord.Interaction, index: int) -> None:
        async with self.lock:
            if self.finished:
                await interaction.response.send_message(
                    "이미 종료된 투표입니다.", ephemeral=True
                )
                return

            user_id = interaction.user.id
            if user_id in self.voters:
                await interaction.response.send_message(
                    "이미 투표에 참여했습니다.", ephemeral=True
                )
                return

            self.voters[user_id] = index
            self.votes[index] += 1
            self.total_votes += 1

            remaining = max(self.target_count - self.total_votes, 0)
            if self.total_votes >= self.target_count:
                self.status_text = STATUS_COMPLETED
                await interaction.response.send_message(
                    f"✅ `{self.options[index]}`에 투표 완료! 목표 인원이 충족되어 투표를 종료합니다.",
                    ephemeral=True,
                )
                await self.finalize(send_followup=True)
            else:
                await interaction.response.send_message(
                    f"✅ `{self.options[index]}`에 투표했습니다! 남은 인원: {remaining}명",
                    ephemeral=True,
                )
                await self.update_message()

    async def update_message(self) -> None:
        if self.message:
            await self.message.edit(embed=self.build_embed(), view=self)

    async def finalize(self, send_followup: bool) -> None:
        if self.finished:
            return
        self.finished = True
        if self.status_text == STATUS_RUNNING:
            self.status_text = STATUS_FINISHED
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        await self.update_message()
        self.stop()

        if send_followup and self.message:
            summary = self._result_text()
            await self.message.channel.send(f"📊 투표 종료! {summary}")


class VoteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("Vote Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> Vote Cog : on ready!")

    @app_commands.command(
        name="투표", description="콤마로 구분한 항목과 참여 인원으로 투표를 진행합니다."
    )
    @app_commands.describe(
        content="콤마(,)로 구분된 투표 항목들",
        count="투표를 종료할 목표 참여 인원 (1~100)",
    )
    @app_commands.rename(content="항목", count="인원")
    async def vote_command(
        self, interaction: discord.Interaction, content: str, count: int
    ):
        items = [entry.strip() for entry in content.split(",") if entry.strip()]

        if len(items) == 0:
            await interaction.response.send_message(
                "❌ 유효한 투표 항목이 없습니다.", ephemeral=True
            )
            return
        if len(items) > 10:
            await interaction.response.send_message(
                "❌ 투표 항목은 최대 10개까지 가능합니다.", ephemeral=True
            )
            return
        if count <= 0:
            await interaction.response.send_message(
                "❌ 투표 인원은 1명 이상이어야 합니다.", ephemeral=True
            )
            return
        if count > 100:
            await interaction.response.send_message(
                "❌ 투표 인원은 최대 100명까지 설정할 수 있습니다.", ephemeral=True
            )
            return

        view = VoteView(self, items, count, interaction.user)

        await interaction.response.send_message(embed=view.build_embed(), view=view)
        original_message = await interaction.original_response()
        await view.bind_message(original_message)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoteCog(bot))
    print("Vote Cog : setup 완료!")
