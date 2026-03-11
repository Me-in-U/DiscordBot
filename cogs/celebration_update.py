import discord
from discord import app_commands
from discord.ext import commands

from util.celebration import refresh_celebration_messages


class CelebrationUpdate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="기념일업데이트",
        description="오늘의 기념일 및 사건 메시지를 수정하여 갱신합니다.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def celebration_update(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "이 명령어는 길드에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "길드 멤버만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "관리자 권한이 있는 사용자만 기념일 공지를 갱신할 수 있습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        results = await refresh_celebration_messages(
            self.bot,
            guild_id=int(interaction.guild_id),
        )
        result = results[0] if results else None

        if result is None or result.status != "ok" or result.channel_id is None:
            error_message = (
                result.error
                if result is not None and result.error
                else "기념일 공지를 갱신하지 못했습니다."
            )
            await interaction.followup.send(error_message, ephemeral=True)
            return

        if result.action == "edited":
            summary = f"<#{result.channel_id}> 채널의 오늘 기념일 공지를 수정했습니다."
        else:
            summary = (
                f"<#{result.channel_id}> 채널에 오늘 기념일 공지가 없어 새로 전송했습니다."
            )

        await interaction.followup.send(summary, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CelebrationUpdate(bot))
    print("CelebrationUpdate Cog : setup 완료!")
