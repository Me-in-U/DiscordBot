from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from util.channel_settings import get_settings_for_guild, set_channel

PURPOSE_CHOICES = {
    "celebration": "기념일",
    "gamble": "도박",
    "music": "음악",
    "youtube": "유튜브",
}


class ChannelSettings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="채널설정",
        description="기념일, 도박, 음악, 유튜브 기능이 동작할 채널을 지정하거나 해제합니다.",
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
        celebration = summary.get("celebration")
        gamble = summary.get("gamble")
        music = summary.get("music")
        youtube = summary.get("youtube")

        embed = discord.Embed(
            title="⚙️ 채널 설정",
            description=(
                f"`{PURPOSE_CHOICES[purpose.value]}` 기능 채널을 {action}했습니다."
                f"\n→ {PURPOSE_CHOICES[purpose.value]} 채널: {channel_text}"
            ),
            color=discord.Color.blurple(),
        )
        celebration_value = f"<#{celebration}>" if celebration else "미지정"
        gamble_value = f"<#{gamble}>" if gamble else "미지정"
        music_value = f"<#{music}>" if music else "미지정"
        youtube_value = f"<#{youtube}>" if youtube else "미지정"

        embed.add_field(
            name="현재 기념일 채널",
            value=celebration_value,
            inline=True,
        )
        embed.add_field(
            name="현재 도박 채널",
            value=gamble_value,
            inline=True,
        )
        embed.add_field(
            name="현재 음악 채널",
            value=music_value,
            inline=True,
        )
        embed.add_field(
            name="현재 유튜브 채널",
            value=youtube_value,
            inline=True,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="채널설정확인",
        description="현재 길드에 설정된 기념일/도박/음악/유튜브 채널을 확인합니다.",
    )
    async def show_channel_settings(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "이 명령어는 길드에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        summary = await get_settings_for_guild(int(interaction.guild_id))
        celebration = summary.get("celebration")
        gamble = summary.get("gamble")
        music = summary.get("music")
        youtube = summary.get("youtube")

        embed = discord.Embed(title="🔎 채널 설정 현황", color=discord.Color.blurple())
        celebration_value = f"<#{celebration}>" if celebration else "미지정"
        gamble_value = f"<#{gamble}>" if gamble else "미지정"
        music_value = f"<#{music}>" if music else "미지정"
        youtube_value = f"<#{youtube}>" if youtube else "미지정"

        embed.add_field(
            name="기념일",
            value=celebration_value,
            inline=True,
        )
        embed.add_field(
            name="도박",
            value=gamble_value,
            inline=True,
        )
        embed.add_field(
            name="음악",
            value=music_value,
            inline=True,
        )
        embed.add_field(
            name="유튜브",
            value=youtube_value,
            inline=True,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelSettings(bot))
    print("ChannelSettings Cog : setup 완료!")
