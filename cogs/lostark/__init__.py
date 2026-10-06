import logging

import discord
from discord import app_commands
from discord.ext import commands

from util.lostark.notices import configure_lostark_notice_channel

logger = logging.getLogger(__name__)


class LostArkCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="로아공지구독", description="현재 채널에서 로스트아크 새 공지와 수정 공지 알림을 받거나 해제합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(status="true면 현재 채널로 구독하고 false면 구독을 해제합니다.")
    @app_commands.rename(status="상태")
    async def configure_subscription(self, interaction: discord.Interaction, status: bool):
        if interaction.guild_id is None or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("길드 관리자만 로스트아크 공지 구독을 설정할 수 있습니다.", ephemeral=True)
            return
        if status and interaction.channel_id is None:
            await interaction.response.send_message("현재 채널을 확인할 수 없습니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await configure_lostark_notice_channel(interaction.guild_id, interaction.channel_id if status else None)
        except Exception:
            logger.exception("로스트아크 공지 구독 설정 실패: guild=%s", interaction.guild_id)
            await interaction.followup.send("로스트아크 공지 구독 설정에 실패했습니다. 잠시 후 다시 시도해 주세요.", ephemeral=True)
            return
        await interaction.followup.send(
            f"로스트아크 공지 구독을 {'설정' if status else '해제'}했습니다."
            + (f"\n알림 채널: <#{interaction.channel_id}>\n기존 공지는 건너뛰고 새 공지와 수정 공지부터 알립니다." if status else ""),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(LostArkCommands(bot))
