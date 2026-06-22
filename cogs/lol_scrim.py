from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from util.lol.scrim import (
    MAX_SCRIM_PLAYERS,
    LolScrimMatch,
    build_lol_scrim_match,
    format_lol_scrim_team_slots,
    parse_extra_players,
)


def _build_lol_scrim_embed(
    match: LolScrimMatch,
    *,
    voice_channel_name: str,
    extra_count: int,
    excluded_text: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="롤 내전 팀 배정",
        description="레드/블루팀과 포지션을 랜덤 배정했습니다.",
        color=discord.Color.red(),
    )
    embed.add_field(
        name="레드팀",
        value=format_lol_scrim_team_slots(match.red),
        inline=True,
    )
    embed.add_field(
        name="블루팀",
        value=format_lol_scrim_team_slots(match.blue),
        inline=True,
    )
    embed.add_field(
        name="배정 정보",
        value=(
            f"기준 음성방: **{voice_channel_name}**\n"
            f"추가 인원: **{extra_count}명**\n"
            f"제외 인원: **{excluded_text}**"
        ),
        inline=False,
    )
    embed.set_footer(text="10명 미만이면 인원1, 인원2처럼 빈 자리를 채웁니다.")
    return embed


class LolScrimCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("LolScrimCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> LolScrimCommands Cog : on ready!")

    @app_commands.command(
        name="내전",
        description="현재 음성방 인원으로 롤 내전 레드/블루팀을 랜덤 배정합니다.",
    )
    @app_commands.describe(
        extra_people="음성방 밖에서 추가할 사람 이름입니다. 여러 명은 쉼표, 세미콜론, 줄바꿈으로 구분하세요.",
        excluded_member="현재 음성방 인원 중 배정에서 뺄 사람입니다.",
    )
    @app_commands.rename(extra_people="추가할사람", excluded_member="뺄사람")
    async def create_lol_scrim(
        self,
        interaction: discord.Interaction,
        extra_people: str | None = None,
        excluded_member: discord.Member | None = None,
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

        voice_state = interaction.user.voice
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "내전 팀 배정은 명령어를 입력한 사람이 음성방에 들어가 있어야 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        voice_channel = voice_state.channel
        if excluded_member is not None:
            excluded_voice_state = excluded_member.voice
            if (
                excluded_voice_state is None
                or excluded_voice_state.channel is None
                or excluded_voice_state.channel.id != voice_channel.id
            ):
                await interaction.response.send_message(
                    "`뺄사람`은 현재 같은 음성방에 있는 유저만 선택할 수 있습니다.",
                    ephemeral=True,
                )
                return

        voice_players = [
            member.display_name
            for member in voice_channel.members
            if not member.bot
            and (excluded_member is None or member.id != excluded_member.id)
        ]
        extra_player_names = parse_extra_players(extra_people)
        total_players = len(voice_players) + len(extra_player_names)
        if total_players > MAX_SCRIM_PLAYERS:
            await interaction.response.send_message(
                (
                    f"내전 인원은 최대 {MAX_SCRIM_PLAYERS}명까지 가능합니다.\n"
                    f"현재 음성방 {len(voice_players)}명 + 추가 {len(extra_player_names)}명 = "
                    f"{total_players}명입니다."
                ),
                ephemeral=True,
            )
            return

        match = build_lol_scrim_match(voice_players, extra_player_names)
        excluded_text = excluded_member.display_name if excluded_member else "없음"
        embed = _build_lol_scrim_embed(
            match,
            voice_channel_name=voice_channel.name,
            extra_count=len(extra_player_names),
            excluded_text=excluded_text,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LolScrimCommands(bot))
    print("LolScrimCommands Cog : setup 완료!")
