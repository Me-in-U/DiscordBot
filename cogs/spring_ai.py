import os

import discord
from discord import app_commands
from discord.ext import commands

TEST_GUILD_ID = int(os.getenv("GUILD_ID"))


class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 기본값 설정
        if not hasattr(self.bot, "SPRING_AI_MODE"):
            self.bot.SPRING_AI_MODE = False
        if not hasattr(self.bot, "SPRING_AI_STYLE"):
            self.bot.SPRING_AI_STYLE = "공격적"
        print("AICog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> AICog : on ready!")

    @app_commands.command(
        name="ai", description="AI 모드를 활성화하거나 비활성화합니다."
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="활성화", value="activate"),
            app_commands.Choice(name="비활성화", value="deactivate"),
        ]
    )
    async def ai_toggle(
        self, interaction: discord.Interaction, action: app_commands.Choice[str]
    ):
        """AI 모드 활성화/비활성화"""
        if action.value == "activate":
            self.bot.SPRING_AI_MODE = True
            msg = "AI 모드가 활성화되었습니다."
        else:
            self.bot.SPRING_AI_MODE = False
            msg = "AI 모드가 비활성화되었습니다."

        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="ai성격", description="AI 응답 스타일을 설정합니다.")
    @app_commands.choices(
        style=[
            app_commands.Choice(name="공격적", value="공격적"),
            app_commands.Choice(name="친절", value="친절"),
        ]
    )
    async def ai_style(
        self, interaction: discord.Interaction, style: app_commands.Choice[str]
    ):
        """AI 응답 톤(공격적 또는 친절) 설정"""
        self.bot.SPRING_AI_STYLE = style.value
        msg = f"AI 성격이 '{style.name}' 모드로 설정되었습니다."
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AICog(bot))
    print("AICog : setup 완료!")
