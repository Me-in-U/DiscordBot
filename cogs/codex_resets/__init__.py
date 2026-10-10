import logging

import discord
from discord import app_commands
from discord.ext import commands

from util.codex_resets.events import (
    CODEX_RESET_CHANNEL_TYPE,
    seed_codex_reset_state_for_guild,
)
from util.guild.channel_settings import set_channel
from util.codex_resets.tibo import reset_tibo_daily_log_state


logger = logging.getLogger(__name__)


class CodexResetCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("CodexResetCommands Cog : init 로드 완료!")

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
            "관리자 권한이 있는 사용자만 Codex 리셋 알림을 설정할 수 있습니다.",
            ephemeral=True,
        )
        return False

    @app_commands.command(
        name="코덱스리셋알림",
        description="현재 채널에서 Codex 리셋과 Tibo Daily log 알림을 받거나 해제합니다.",
    )
    @app_commands.describe(
        status="true면 현재 채널로 알림을 받고 false면 알림을 해제합니다."
    )
    @app_commands.rename(status="상태")
    async def configure_codex_reset_notification(
        self,
        interaction: discord.Interaction,
        status: bool,
    ) -> None:
        if not await self._require_guild_admin(interaction):
            return

        guild_id = int(interaction.guild_id)
        if not status:
            await set_channel(guild_id, CODEX_RESET_CHANNEL_TYPE, None)
            await reset_tibo_daily_log_state(guild_id)
            await interaction.response.send_message(
                "Codex 리셋과 Tibo Daily log 알림을 해제했습니다.",
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
        await set_channel(guild_id, CODEX_RESET_CHANNEL_TYPE, channel_id)
        await reset_tibo_daily_log_state(guild_id)

        try:
            seeded_count = await seed_codex_reset_state_for_guild(guild_id)
        except Exception:
            logger.exception(
                "Codex 리셋 알림 초기 상태 저장 실패: guild_id=%s",
                guild_id,
            )
            await interaction.followup.send(
                "Codex 리셋과 Tibo Daily log 알림을 설정했습니다.\n"
                "Daily log는 첫 확인 이후 새 발표와 내용 수정을 알립니다.\n"
                "다만 최신 리셋 초기 상태 저장에 실패해 다음 확인 때 초기화됩니다.",
                ephemeral=True,
            )
            return

        seed_message = (
            "현재 최신 리셋 1건은 전송하지 않고 이후 새 리셋만 알립니다."
            if seeded_count
            else "현재 리셋 이력이 없어 다음 새 리셋부터 알립니다."
        )
        await interaction.followup.send(
            "Codex 리셋과 Tibo Daily log 알림을 설정했습니다.\n"
            f"알림 채널: <#{channel_id}>\n"
            f"{seed_message}\n"
            "Daily log는 첫 확인 이후 새 발표와 내용 수정을 알립니다.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CodexResetCommands(bot))
    print("CodexResetCommands Cog : setup 완료!")
