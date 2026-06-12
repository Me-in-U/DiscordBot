import traceback

import discord
from discord import app_commands
from discord.ext import commands

from util.maplestory_events import MapleStoryEvent, fetch_sunday_maple_event


class MapleStoryCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("MapleStoryCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> MapleStoryCommands Cog : on ready!")

    @app_commands.command(
        name="썬데이메이플",
        description="진행 중인 스페셜 썬데이 메이플 이벤트 본문 이미지를 보여줍니다.",
    )
    async def sunday_maple(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            event = await fetch_sunday_maple_event()
        except Exception:
            traceback.print_exc()
            await interaction.followup.send(
                "⚠️ 메이플스토리 이벤트 정보를 가져오는 중 오류가 발생했습니다.",
                ephemeral=True,
            )
            return

        if event is None:
            await interaction.followup.send(
                "현재 진행중인 이벤트에 스페셜 썬데이 메이플이 없습니다."
            )
            return

        if not event.image_urls:
            await interaction.followup.send(
                f"스페셜 썬데이 메이플 이벤트는 찾았지만 본문 이미지를 찾지 못했습니다.\n{event.url}"
            )
            return

        await interaction.followup.send(embeds=self._build_event_embeds(event))

    def _build_event_embeds(self, event: MapleStoryEvent) -> list[discord.Embed]:
        embeds: list[discord.Embed] = []
        for index, image_url in enumerate(event.image_urls[:10], start=1):
            embed = discord.Embed(
                title=event.title if index == 1 else f"{event.title} ({index})",
                url=event.url,
                description=event.period or None,
                color=discord.Color.green(),
            )
            embed.set_image(url=image_url)
            embed.set_footer(text="출처: 메이플스토리 공식 이벤트")
            embeds.append(embed)
        return embeds


async def setup(bot: commands.Bot):
    await bot.add_cog(MapleStoryCommands(bot))
    print("MapleStoryCommands Cog : setup 완료!")
