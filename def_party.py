import json
from datetime import datetime, time, timedelta, timezone

from discord.ext import commands, tasks


class Party(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.load_settings()  # 초기 설정 로드
        print("Party Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT on_ready() -> Party Cog : on ready!")

    def load_settings(self):
        """JSON 파일에서 초기 설정을 로드합니다."""
        with open(self.bot.SETTING_DATA, "r", encoding="utf-8") as file:
            settings = json.load(file)

    def save_settings(self):
        """현재 설정을 JSON 파일에 저장합니다."""
        with open(self.bot.SETTING_DATA, "r", encoding="utf-8") as file:
            settings = json.load(file)
        with open(self.bot.SETTING_DATA, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=4)

    # @commands.command(
    #     aliases=["솔랭"], help="입력한 닉네임#태그의 솔로 랭크 정보를 출력합니다."
    # )
    # async def print_solo_rank(self, ctx, *, text: str = None):
    #     print("asd")


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(Party(bot))
    print("Party Cog : setup 완료!")
