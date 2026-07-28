from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from util.earthquake.alerts import EARTHQUAKE_ALERT_CHANNEL_TYPE
from util.earthquake.state import delete_earthquake_alert_state
from util.guild.channel_settings import set_channel


class EarthquakeAlertCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("EarthquakeAlertCommands Cog : init 로드 완료!")

    async def _require_guild_admin(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "이 명령어는 길드에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "길드 멤버만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message(
            "관리자 권한이 있는 사용자만 일본 지진 알림을 설정할 수 있습니다.",
            ephemeral=True,
        )
        return False

    @app_commands.command(
        name="지진알림",
        description="현재 채널에서 일본 M5.5 이상 긴급지진속보 알림을 받거나 해제합니다.",
    )
    @app_commands.describe(
        status="true면 현재 채널로 알림을 받고 false면 알림을 해제합니다."
    )
    @app_commands.rename(status="상태")
    async def configure_earthquake_alert(
        self,
        interaction: discord.Interaction,
        status: bool,
    ) -> None:
        if not await self._require_guild_admin(interaction):
            return

        guild_id = int(interaction.guild_id)
        if not status:
            await set_channel(guild_id, EARTHQUAKE_ALERT_CHANNEL_TYPE, None)
            await delete_earthquake_alert_state(guild_id)
            await interaction.response.send_message(
                "일본 지진 알림을 해제했습니다.",
                ephemeral=True,
            )
            return

        if interaction.channel_id is None:
            await interaction.response.send_message(
                "현재 채널을 확인할 수 없어 알림을 설정하지 못했습니다.",
                ephemeral=True,
            )
            return

        channel_id = int(interaction.channel_id)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await set_channel(
            guild_id,
            EARTHQUAKE_ALERT_CHANNEL_TYPE,
            channel_id,
        )
        await delete_earthquake_alert_state(guild_id)
        await interaction.followup.send(
            "일본 지진 알림을 설정했습니다.\n"
            f"알림 채널: <#{channel_id}>\n"
            "일본 M5.5 이상 긴급지진속보부터 실시간으로 알립니다.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EarthquakeAlertCommands(bot))
    print("EarthquakeAlertCommands Cog : setup 완료!")
