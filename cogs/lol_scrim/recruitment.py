from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import discord

from common.discord_ui import SafeView
from util.lol.scrim import (
    MAX_SCRIM_PLAYERS,
    LolScrimMatch,
    LolScrimRoster,
    build_lol_scrim_match,
    format_lol_scrim_roster,
    format_lol_scrim_team_slots,
)


logger = logging.getLogger(__name__)
SCRIM_RECRUITMENT_TIMEOUT_SECONDS = 600.0


def _build_lol_scrim_recruitment_embed(
    roster: LolScrimRoster,
    *,
    voice_channel_name: str,
    owner_display_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="롤 내전 참가자 모집",
        description=(
            "기준 음성방에 참가한 상태로 아래 `참가` 버튼을 눌러주세요.\n"
            "10명이 모이면 레드팀과 블루팀, 포지션을 자동으로 배정합니다."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name=f"참가 현황 {roster.count}/{MAX_SCRIM_PLAYERS}",
        value=format_lol_scrim_roster(roster.labels()),
        inline=False,
    )
    embed.add_field(
        name="기준 음성방",
        value=f"**{voice_channel_name}**",
        inline=False,
    )
    embed.set_footer(
        text=f"모집자: {owner_display_name} | 10분 동안 참가자를 모집합니다."
    )
    return embed


def _build_lol_scrim_embed(
    match: LolScrimMatch,
    *,
    voice_channel_name: str,
    owner_display_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="롤 내전 팀 배정 완료",
        description="참가자 10명이 모두 모여 팀과 포지션을 무작위로 배정했습니다.",
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
            f"참가 인원: **{MAX_SCRIM_PLAYERS}명**\n"
            f"모집자: **{owner_display_name}**"
        ),
        inline=False,
    )
    embed.set_footer(text="참가 순서와 관계없이 모든 참가자를 무작위로 배정했습니다.")
    return embed


def _build_lol_scrim_closed_embed(
    roster: LolScrimRoster,
    *,
    voice_channel_name: str,
    owner_display_name: str,
    timed_out: bool,
) -> discord.Embed:
    if timed_out:
        title = "롤 내전 모집 종료"
        description = (
            "10분 동안 참가자 10명이 모이지 않아 모집을 자동으로 종료했습니다."
        )
        color = discord.Color.dark_grey()
    else:
        title = "롤 내전 모집 취소"
        description = f"{owner_display_name}님이 내전 참가자 모집을 취소했습니다."
        color = discord.Color.orange()

    embed = discord.Embed(title=title, description=description, color=color)
    embed.add_field(
        name=f"종료 시점 참가 현황 {roster.count}/{MAX_SCRIM_PLAYERS}",
        value=format_lol_scrim_roster(roster.labels()),
        inline=False,
    )
    embed.add_field(
        name="기준 음성방",
        value=f"**{voice_channel_name}**",
        inline=False,
    )
    return embed


class LolScrimRecruitmentView(SafeView):
    def __init__(
        self,
        *,
        guild_id: int,
        voice_channel: discord.VoiceChannel | discord.StageChannel,
        owner_id: int,
        owner_display_name: str,
        release_callback: Callable[["LolScrimRecruitmentView"], None],
    ) -> None:
        super().__init__(timeout=SCRIM_RECRUITMENT_TIMEOUT_SECONDS)
        self.guild_id = guild_id
        self.voice_channel = voice_channel
        self.owner_id = owner_id
        self.owner_display_name = owner_display_name
        self.roster = LolScrimRoster()
        self.message: discord.InteractionMessage | None = None
        self.finished = False
        self._lock = asyncio.Lock()
        self._release_callback = release_callback

    @property
    def voice_channel_id(self) -> int:
        return self.voice_channel.id

    def build_recruitment_embed(self) -> discord.Embed:
        return _build_lol_scrim_recruitment_embed(
            self.roster,
            voice_channel_name=self.voice_channel.name,
            owner_display_name=self.owner_display_name,
        )

    def bind_message(self, message: discord.InteractionMessage) -> None:
        self.message = message

    def _release(self) -> None:
        self._release_callback(self)

    def _disable_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    def _connected_member_ids(self) -> set[int]:
        return {
            member.id
            for member in self.voice_channel.members
            if not member.bot
        }

    @staticmethod
    def _member_voice_channel_id(member: discord.Member) -> int | None:
        voice_state = member.voice
        if voice_state is None or voice_state.channel is None:
            return None
        return voice_state.channel.id

    @staticmethod
    async def _send_private_error(
        interaction: discord.Interaction,
        message: str,
    ) -> None:
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(
        label="참가",
        style=discord.ButtonStyle.success,
        custom_id="lol_scrim_join",
    )
    async def join_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if self.finished:
            await self._send_private_error(interaction, "이미 종료된 내전 모집입니다.")
            return
        if interaction.guild_id != self.guild_id or not isinstance(
            interaction.user, discord.Member
        ):
            await self._send_private_error(
                interaction,
                "이 내전 모집이 시작된 길드의 멤버만 참가할 수 있습니다.",
            )
            return
        if interaction.user.bot:
            await self._send_private_error(interaction, "봇 계정은 참가할 수 없습니다.")
            return
        if self._member_voice_channel_id(interaction.user) != self.voice_channel_id:
            await self._send_private_error(
                interaction,
                f"먼저 `{self.voice_channel.name}` 음성방에 참가해주세요.",
            )
            return

        async with self._lock:
            if self.finished:
                await self._send_private_error(
                    interaction,
                    "이미 종료된 내전 모집입니다.",
                )
                return

            self.roster.retain(self._connected_member_ids())
            if not self.roster.add(interaction.user.id, interaction.user.mention):
                await self._send_private_error(
                    interaction,
                    "이미 내전 참가자로 등록되어 있습니다.",
                )
                return

            if self.roster.is_full:
                match = build_lol_scrim_match(self.roster.labels())
                self.finished = True
                self._disable_buttons()
                embed = _build_lol_scrim_embed(
                    match,
                    voice_channel_name=self.voice_channel.name,
                    owner_display_name=self.owner_display_name,
                )
                try:
                    await interaction.response.edit_message(embed=embed, view=self)
                finally:
                    self.stop()
                    self._release()
                return

            await interaction.response.edit_message(
                embed=self.build_recruitment_embed(),
                view=self,
            )

    @discord.ui.button(
        label="참가 취소",
        style=discord.ButtonStyle.secondary,
        custom_id="lol_scrim_leave",
    )
    async def leave_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if self.finished:
            await self._send_private_error(interaction, "이미 종료된 내전 모집입니다.")
            return
        if interaction.guild_id != self.guild_id:
            await self._send_private_error(
                interaction,
                "이 내전 모집이 시작된 길드에서만 참가를 취소할 수 있습니다.",
            )
            return

        async with self._lock:
            if not self.roster.remove(interaction.user.id):
                await self._send_private_error(
                    interaction,
                    "현재 내전 참가자로 등록되어 있지 않습니다.",
                )
                return
            await interaction.response.edit_message(
                embed=self.build_recruitment_embed(),
                view=self,
            )

    @discord.ui.button(
        label="모집 취소",
        style=discord.ButtonStyle.danger,
        custom_id="lol_scrim_cancel",
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild_permissions = getattr(interaction.user, "guild_permissions", None)
        can_manage_guild = bool(
            guild_permissions and guild_permissions.manage_guild
        )
        if interaction.user.id != self.owner_id and not can_manage_guild:
            await self._send_private_error(
                interaction,
                "내전 모집자 또는 서버 관리자만 모집을 취소할 수 있습니다.",
            )
            return

        async with self._lock:
            if self.finished:
                await self._send_private_error(
                    interaction,
                    "이미 종료된 내전 모집입니다.",
                )
                return
            self.finished = True
            self._disable_buttons()
            embed = _build_lol_scrim_closed_embed(
                self.roster,
                voice_channel_name=self.voice_channel.name,
                owner_display_name=self.owner_display_name,
                timed_out=False,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            finally:
                self.stop()
                self._release()

    async def remove_disconnected_participant(self, user_id: int) -> None:
        async with self._lock:
            if self.finished or not self.roster.remove(user_id):
                return
            if self.message is None:
                return
            try:
                await self.message.edit(
                    embed=self.build_recruitment_embed(),
                    view=self,
                )
            except discord.NotFound:
                self.finished = True
                self.stop()
                self._release()
            except (discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "내전 모집 음성방 이탈 상태 반영 실패: guild_id=%s channel_id=%s",
                    self.guild_id,
                    self.voice_channel_id,
                    exc_info=True,
                )

    async def on_timeout(self) -> None:
        async with self._lock:
            if self.finished:
                return
            self.finished = True
            self._disable_buttons()
            self.stop()
            self._release()
            if self.message is None:
                return
            try:
                await self.message.edit(
                    embed=_build_lol_scrim_closed_embed(
                        self.roster,
                        voice_channel_name=self.voice_channel.name,
                        owner_display_name=self.owner_display_name,
                        timed_out=True,
                    ),
                    view=self,
                )
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logger.warning(
                    "시간 초과 내전 모집 메시지 갱신 실패: guild_id=%s channel_id=%s",
                    self.guild_id,
                    self.voice_channel_id,
                    exc_info=True,
                )
