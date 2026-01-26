import json
from util.db import execute_query, fetch_one
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
        key = "youtubeLiveChecker"
        try:
            # DB 로드
            query = "SELECT setting_value FROM setting_data WHERE setting_key = %s"
            row = await fetch_one(query, (key,))
            val = {}
            if row and row["setting_value"]:
                val = (
                    json.loads(row["setting_value"])
                    if isinstance(row["setting_value"], str)
                    else row["setting_value"]
                )

            # 값 변경
            val["loop"] = action.value == "on"
            status = "켜졌습니다" if action.value == "on" else "꺼졌습니다"

            # DB 저장
            json_str = json.dumps(val, ensure_ascii=False)
            q2 = "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = %s"
            await execute_query(q2, (key, json_str, json_str))

            # Cog 제어
            cog = self.bot.get_cog("LoopTasks")
            if cog:
                loop_task = cog.youtube_live_check
                if action.value == "on":
                    if not loop_task.is_running():
                        loop_task.start()
                else:
                    if loop_task.is_running():
                        loop_task.stop()

            # 사용자 응답
            await interaction.response.send_message(
                f"✅ YouTube 라이브 체크가 **{status}**.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"오류: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(YoutubeCheckerCog(bot))
    print("YoutubeCheckerCog: setup 완료!")
