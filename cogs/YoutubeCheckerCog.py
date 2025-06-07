import json
import os

import discord
from discord import app_commands
from discord.ext import commands


class YoutubeCheckerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("YoutubeCheckerCog: init 완료!")

    @app_commands.command(
        name="유투브라이브체커", description="유튜브 라이브 체크 루프를 켜거나 끕니다."
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="켜기", value="on"),
            app_commands.Choice(name="끄기", value="off"),
        ]
    )
    async def toggle_live_checker(
        self, interaction: discord.Interaction, action: app_commands.Choice[str]
    ):
        # 설정 파일 로드
        path = self.bot.SETTING_DATA
        with open(path, "r", encoding="utf-8") as f:
            settings = json.load(f)

        if action.value == "on":
            settings["youtubeLiveChecker"]["loop"] = True
            # Cog 내 루프 시작
            self.bot.get_cog("LoopTasks").youtube_live_check.start()
            msg = "✅ YouTube 라이브 체크가 **켜졌습니다**."
        else:
            settings["youtubeLiveChecker"]["loop"] = False
            # Cog 내 루프 중단
            self.bot.get_cog("LoopTasks").youtube_live_check.stop()
            msg = "❌ YouTube 라이브 체크가 **꺼졌습니다**."

        # 설정 파일 저장
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)

        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(YoutubeCheckerCog(bot))
    print("YoutubeCheckerCog: setup 완료!")
