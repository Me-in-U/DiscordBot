import json

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
    async def toggle_live_checker(self, interaction, action: app_commands.Choice[str]):
        # 1) 설정 파일 경로 로깅
        path = self.bot.SETTING_DATA
        print(f"[유튜브체커] SETTING_DATA path = {path}")

        # 2) 파일 로드
        try:
            with open(path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception as e:
            print(f"[유튜브체커] 설정 파일 로드 실패: {e}")
            await interaction.response.send_message(
                "⚠ 설정 파일을 읽을 수 없습니다.", ephemeral=True
            )
            return

        # 3) loop 값 변경
        settings["youtubeLiveChecker"]["loop"] = action.value == "on"
        status = "켜졌습니다" if action.value == "on" else "꺼졌습니다"

        # 4) 변경된 settings 로깅
        print(f"[유튜브체커] 변경 후 settings = {settings['youtubeLiveChecker']}")

        # 5) 파일 저장
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
            print("[유튜브체커] 설정 파일 저장 완료")
        except Exception as e:
            print(f"[유튜브체커] 설정 파일 저장 실패: {e}")
            await interaction.response.send_message(
                "⚠ 설정 파일을 쓸 수 없습니다.", ephemeral=True
            )
            return

        # 6) 루프 start/stop
        # Cog 내에서
        cog = self.bot.get_cog("LoopTasks")
        loop_task = cog.youtube_live_check

        if action.value == "on":
            settings["youtubeLiveChecker"]["loop"] = True
            if not loop_task.is_running():
                loop_task.start()
            msg = "✅ YouTube 라이브 체크가 **켜졌습니다**."
        else:
            settings["youtubeLiveChecker"]["loop"] = False
            if loop_task.is_running():
                loop_task.stop()
            msg = "❌ YouTube 라이브 체크가 **꺼졌습니다**."

        # 7) 사용자 응답
        await interaction.response.send_message(
            f"✅ YouTube 라이브 체크가 **{status}**.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(YoutubeCheckerCog(bot))
    print("YoutubeCheckerCog: setup 완료!")
