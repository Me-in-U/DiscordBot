import discord
from discord import app_commands
from discord.ext import commands


class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("Ping Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> Ping Cog : on ready!")

    @app_commands.command(name="핑", description="봇과의 핑(지연 시간)을 출력합니다.")
    async def ping(self, interaction: discord.Interaction):
        ws_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"퐁! WebSocket 지연: {ws_ms}ms")


async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))
    print("Ping Cog : setup 완료!")
