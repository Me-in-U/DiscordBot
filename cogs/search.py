import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import web_search


class SearchCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("SearchCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> SearchCommands Cog : on ready!")

    @app_commands.command(
        name="검색",
        description="웹에서 최신 정보를 검색합니다. 텍스트 매개변수로 검색어를 입력하세요.",
    )
    @app_commands.describe(내용="검색할 내용을 입력하세요.")
    async def search(self, interaction: discord.Interaction, 내용: str):
        # 슬래시 커맨드 응답을 대기 상태로 둡니다.
        await interaction.response.defer(thinking=True)

        try:
            # 서울 지역을 기준으로 웹 검색 수행
            response = web_search(
                query=내용, model="gpt-4o-mini-search-preview-2025-03-11"
            )
        except Exception as e:
            response = f"Error: {e}"

        await interaction.followup.send(response)


async def setup(bot):
    await bot.add_cog(SearchCommands(bot))
    print("SearchCommands Cog : setup 완료!")
