from discord import app_commands
from discord.ext import commands


class YoutubeCheckerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("YoutubeCheckerCog: init 완료!")

    @app_commands.command(
        name="유투브라이브체커",
        description="유튜브 구독 기반 자동 체커 안내를 표시합니다.",
    )
    async def toggle_live_checker(self, interaction):
        await interaction.response.send_message(
            "유튜브 라이브 체커는 이제 `/유튜브구독` 목록을 기준으로 자동 동작합니다.\n"
            "`/채널설정 기능:유튜브`로 알림 채널을 지정한 뒤 "
            "`/유튜브구독 추가`를 사용해 주세요.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(YoutubeCheckerCog(bot))
    print("YoutubeCheckerCog: setup 완료!")
