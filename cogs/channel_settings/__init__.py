from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from util.guild.channel_settings import get_settings_for_guild, set_channel

PURPOSE_CHOICES = {
    "celebration": "기념일",
    "gamble": "도박",
    "music": "음악",
    "youtube": "유튜브",
    "maplestory_notice": "메이플공지",
}
PURPOSE_DESCRIPTION = "기념일/도박/음악/유튜브/메이플공지"


def _add_current_channel_fields(
    embed: discord.Embed,
    summary: dict[str, int],
) -> None:
    for purpose_key, purpose_label in PURPOSE_CHOICES.items():
        channel_id = summary.get(purpose_key)
        channel_value = f"<#{channel_id}>" if channel_id else "미지정"
        embed.add_field(
            name=f"현재 {purpose_label} 채널",
            value=channel_value,
            inline=True,
        )


class ChannelSettings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="채널설정",
        description=f"{PURPOSE_DESCRIPTION} 기능이 동작할 채널을 지정하거나 해제합니다.",
    )
    @app_commands.describe(
        purpose="설정할 기능 타입을 선택하세요.",
        channel="동작할 채널 (비워두면 설정을 해제합니다)",
    )
    @app_commands.rename(purpose="기능", channel="채널")
    @app_commands.choices(
        purpose=[
            app_commands.Choice(name="기념일", value="celebration"),
            app_commands.Choice(name="도박", value="gamble"),
            app_commands.Choice(name="음악", value="music"),
            app_commands.Choice(name="유튜브", value="youtube"),
            app_commands.Choice(name="메이플공지", value="maplestory_notice"),
        ]
    )
    async def configure_channel(
        self,
        interaction: discord.Interaction,
        purpose: app_commands.Choice[str],
        channel: discord.TextChannel | None = None,
    ) -> None:
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
                "관리자 권한이 있는 사용자만 채널을 설정할 수 있습니다.",
                ephemeral=True,
            )
            return

        guild_id = int(interaction.guild_id)
        await set_channel(guild_id, purpose.value, channel.id if channel else None)

        action = "해제" if channel is None else "설정"
        channel_text = "설정 해제" if channel is None else channel.mention

        summary = await get_settings_for_guild(guild_id)

        embed = discord.Embed(
            title="⚙️ 채널 설정",
            description=(
                f"`{PURPOSE_CHOICES[purpose.value]}` 기능 채널을 {action}했습니다."
                f"\n→ {PURPOSE_CHOICES[purpose.value]} 채널: {channel_text}"
            ),
            color=discord.Color.blurple(),
        )
        _add_current_channel_fields(embed, summary)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="채널설정확인",
        description=f"현재 길드에 설정된 {PURPOSE_DESCRIPTION} 채널을 확인합니다.",
    )
    async def show_channel_settings(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "이 명령어는 길드에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        summary = await get_settings_for_guild(int(interaction.guild_id))

        embed = discord.Embed(title="🔎 채널 설정 현황", color=discord.Color.blurple())
        _add_current_channel_fields(embed, summary)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelSettings(bot))
    print("ChannelSettings Cog : setup 완료!")
