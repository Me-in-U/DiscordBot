from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.lol_scrim.recruitment import LolScrimRecruitmentView


class LolScrimCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._active_recruitments: dict[int, LolScrimRecruitmentView] = {}
        print("LolScrimCommands Cog : init 로드 완료!")

    def cog_unload(self) -> None:
        for view in self._active_recruitments.values():
            view.stop()
        self._active_recruitments.clear()

    def _release_recruitment(self, view: LolScrimRecruitmentView) -> None:
        active_view = self._active_recruitments.get(view.voice_channel_id)
        if active_view is view:
            del self._active_recruitments[view.voice_channel_id]

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        print("DISCORD_CLIENT -> LolScrimCommands Cog : on ready!")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel is None:
            return
        if after.channel is not None and after.channel.id == before.channel.id:
            return

        view = self._active_recruitments.get(before.channel.id)
        if view is not None:
            await view.remove_disconnected_participant(member.id)

    @app_commands.command(
        name="내전",
        description="음성방 참가자 10명을 모집해 롤 내전 팀과 포지션을 배정합니다.",
    )
    async def create_lol_scrim(
        self,
        interaction: discord.Interaction,
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
                "내전 참가자 모집은 명령어를 입력한 사람이 음성방에 들어가 있어야 시작할 수 있습니다.",
                ephemeral=True,
            )
            return

        voice_channel = voice_state.channel
        if not isinstance(voice_channel, (discord.VoiceChannel, discord.StageChannel)):
            await interaction.response.send_message(
                "일반 음성방이나 스테이지 채널에서만 내전 모집을 시작할 수 있습니다.",
                ephemeral=True,
            )
            return

        active_view = self._active_recruitments.get(voice_channel.id)
        if active_view is not None and not active_view.finished:
            message_link = (
                f" 기존 모집: {active_view.message.jump_url}"
                if active_view.message is not None
                else ""
            )
            await interaction.response.send_message(
                f"이 음성방에서는 이미 내전 참가자를 모집하고 있습니다.{message_link}",
                ephemeral=True,
            )
            return

        view = LolScrimRecruitmentView(
            guild_id=interaction.guild_id,
            voice_channel=voice_channel,
            owner_id=interaction.user.id,
            owner_display_name=interaction.user.display_name,
            release_callback=self._release_recruitment,
        )
        self._active_recruitments[voice_channel.id] = view
        try:
            await interaction.response.send_message(
                embed=view.build_recruitment_embed(),
                view=view,
            )
            view.bind_message(await interaction.original_response())
        except Exception:
            self._release_recruitment(view)
            view.stop()
            raise


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LolScrimCommands(bot))
    print("LolScrimCommands Cog : setup 완료!")
