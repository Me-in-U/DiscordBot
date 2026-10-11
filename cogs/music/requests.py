from __future__ import annotations

from typing import Any
import discord
from util.music.logging import build_music_play_command_debug_message
from util.music.state import GuildMusicState
from util.music.search import is_http_url
from util.music.playback import (
    MusicPlayerPreparationError,
    build_prepared_playback_start,
    prepare_music_player,
)
from util.music.playback_actions import (
    UrlPlayActionResult,
    begin_play_url_now_playback_action,
    begin_url_play_action,
    complete_play_url_now_playback_action,
)
from util.music.source import YTDLSource
from util.music.voice import (
    describe_voice_transition,
    ensure_music_voice_client,
    get_interaction_voice_channel,
    is_voice_client_active,
)
from .runtime import dbg


class MusicRequestsMixin:
    async def _ensure_play_url_now_voice_client(
        self,
        interaction: discord.Interaction,
    ) -> Any | None:
        user_channel = get_interaction_voice_channel(interaction)
        voice_result = await ensure_music_voice_client(
            voice_client=interaction.guild.voice_client,
            user_channel=user_channel,
            missing_channel_message="❌ 먼저 음성 채널에 들어가 있어야 합니다.",
            busy_channel_message="❌ 같은 음성 채널에 있는 사용자만 음악을 제어할 수 있습니다.",
        )
        if voice_result.error_message:
            await self._send_auto_delete(
                interaction,
                voice_result.error_message,
            )
            return None
        voice_client = voice_result.voice_client
        if voice_client is None:
            return None
        if transition_log := describe_voice_transition(
            voice_result,
            action="_play_url_now",
            user_channel=user_channel,
        ):
            dbg(transition_log)
        return voice_client

    async def _prepare_play_url_now_player(
        self,
        interaction: discord.Interaction,
        url: str,
    ) -> Any | None:
        try:
            return await prepare_music_player(
                YTDLSource.from_url,
                url,
                loop=self.bot.loop,
                requester=interaction.user,
            )
        except MusicPlayerPreparationError as exc:
            dbg(f"_play_url_now: {exc.failure.debug_message}")
            await self._send_auto_delete(
                interaction,
                exc.failure.user_message,
                delay=exc.failure.delete_after,
            )
            return None

    async def _start_play_url_now_prepared_playback(
        self,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        state: GuildMusicState,
        player: Any,
        success_prefix: str,
        replacing: bool,
    ) -> None:
        playback_start = build_prepared_playback_start(
            player,
            success_prefix=success_prefix,
        )
        try:
            await self._start_prepared_playback(
                guild_id=guild_id,
                state=state,
                player=player,
                playback_start=playback_start,
            )
        finally:
            complete_play_url_now_playback_action(state, replacing=replacing)

        await self._send_auto_delete(
            interaction,
            playback_start.confirmation_message,
        )

    def _begin_play_url_now_replacement(
        self,
        state: GuildMusicState,
        voice_client: Any,
    ) -> bool:
        replacing = is_voice_client_active(voice_client)
        begin_play_url_now_playback_action(state, replacing=replacing)
        if replacing:
            state.playback_generation += 1
            voice_client.stop()
        return replacing

    async def _prepare_music_url_immediate_player(
        self,
        interaction: discord.Interaction,
        url: str,
    ) -> Any | None:
        try:
            player = await prepare_music_player(
                YTDLSource.from_url,
                url,
                loop=self.bot.loop,
                requester=interaction.user,
                include_ffmpeg_guidance=True,
            )
            dbg(f"_play: prepared player title={getattr(player,'title',None)}")
            return player
        except MusicPlayerPreparationError as exc:
            dbg(f"_play: {exc.failure.debug_message}")
            await self._send_auto_delete(
                interaction,
                exc.failure.user_message,
                delay=exc.failure.delete_after,
            )
            return None

    async def _start_music_url_prepared_playback(
        self,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        state: GuildMusicState,
        player: Any,
    ) -> None:
        playback_start = build_prepared_playback_start(player)
        await self._start_prepared_playback(
            guild_id=guild_id,
            state=state,
            player=player,
            playback_start=playback_start,
        )
        dbg("_play: playback started and updater restarted")
        await self._send_auto_delete(
            interaction,
            playback_start.confirmation_message,
        )

    async def _play_url_now(
        self,
        interaction: discord.Interaction,
        url: str,
        *,
        success_prefix: str = "▶ 재생",
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)

        async with self._music_operation(interaction.guild.id):
            guild_id = interaction.guild.id
            state = self._get_state(guild_id)
            voice_client = await self._ensure_play_url_now_voice_client(interaction)
            if voice_client is None:
                return

            player = await self._prepare_play_url_now_player(interaction, url)
            if player is None:
                return

            replacing = self._begin_play_url_now_replacement(state, voice_client)
            await self._start_play_url_now_prepared_playback(
                interaction,
                guild_id=guild_id,
                state=state,
                player=player,
                success_prefix=success_prefix,
                replacing=replacing,
            )

    async def _start_music_url_immediate_playback(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        state: GuildMusicState,
        url: str,
    ) -> None:
        player = await self._prepare_music_url_immediate_player(interaction, url)
        if player is None:
            return

        await self._start_music_url_prepared_playback(
            interaction,
            guild_id=guild_id,
            state=state,
            player=player,
        )

    async def _send_music_url_queued_response(
        self,
        interaction: discord.Interaction,
        url_play_result: UrlPlayActionResult,
    ) -> None:
        dbg(f"_play: appended URL to queue size={url_play_result.queue_size}")
        if url_play_result.queued_track is not None:
            self._spawn_bg(self._fill_queue_meta(url_play_result.queued_track))
        await self._send_auto_delete(interaction, url_play_result.user_message)

    async def _ensure_music_url_voice_client(
        self,
        interaction: discord.Interaction,
    ) -> Any | None:
        user_channel = get_interaction_voice_channel(interaction)
        voice_result = await ensure_music_voice_client(
            voice_client=interaction.guild.voice_client,
            user_channel=user_channel,
            missing_channel_message="❌ 먼저 음성 채널에 들어가 있어야 합니다.",
            busy_channel_message="❌ 같은 음성 채널에 있는 사용자만 음악을 추가할 수 있습니다.",
        )
        if voice_result.error_message:
            await self._send_auto_delete(
                interaction,
                voice_result.error_message,
            )
            return None
        voice_client = voice_result.voice_client
        if voice_client is None:
            return None
        if transition_log := describe_voice_transition(
            voice_result,
            action="_play",
            user_channel=user_channel,
        ):
            dbg(transition_log)
        return voice_client

    async def _should_start_music_url_immediate_playback(
        self,
        interaction: discord.Interaction,
        state: GuildMusicState,
        voice_client: Any,
        url: str,
    ) -> bool:
        self._cancel_idle_disconnect(state)
        url_play_result = begin_url_play_action(
            state,
            url=url,
            requester=interaction.user,
            is_active=is_voice_client_active(voice_client),
        )
        if not url_play_result.should_prepare:
            await self._send_music_url_queued_response(
                interaction,
                url_play_result,
            )
            return False
        return True

    async def _dispatch_music_url_immediate_playback(
        self,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        state: GuildMusicState,
        voice_client: Any,
        url: str,
    ) -> None:
        should_start_now = await self._should_start_music_url_immediate_playback(
            interaction,
            state,
            voice_client,
            url,
        )
        if not should_start_now:
            return

        await self._start_music_url_immediate_playback(
            interaction,
            guild_id,
            state=state,
            url=url,
        )

    def _get_music_url_branch_context(
        self,
        interaction: discord.Interaction,
    ) -> tuple[int, GuildMusicState]:
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        return guild_id, state

    async def _defer_music_url_branch(
        self,
        interaction: discord.Interaction,
        *,
        skip_defer: bool,
    ) -> None:
        if not skip_defer:
            await interaction.response.defer(thinking=True, ephemeral=True)

    async def _play_music_url_branch(
        self,
        interaction: discord.Interaction,
        url: str,
        *,
        skip_defer: bool = False,
    ) -> None:
        await self._defer_music_url_branch(interaction, skip_defer=skip_defer)

        # ! 기본정보 로드
        async with self._music_operation(interaction.guild.id):
            guild_id, state = self._get_music_url_branch_context(interaction)
            voice_client = await self._ensure_music_url_voice_client(interaction)
            if voice_client is None:
                return

            # ! 이미 재생(또는 일시정지) 중이면 URL만 큐에 추가
            await self._dispatch_music_url_immediate_playback(
                interaction,
                guild_id=guild_id,
                state=state,
                voice_client=voice_client,
                url=url,
            )

    async def _dispatch_music_play_command_branch(
        self,
        interaction: discord.Interaction,
        url: str,
        *,
        skip_defer: bool,
    ) -> None:
        # ? 검색어 처리
        if not is_http_url(url):
            await self._play_music_search_branch(interaction, url)
            # 검색 모드에서는 여기서 종료 (선택은 SelectView가 처리)
            return

        # ? URL 재생
        await self._play_music_url_branch(
            interaction,
            url,
            skip_defer=skip_defer,
        )

    async def _play(
        self,
        interaction: discord.Interaction,
        url: str,
        skip_defer: bool = False,
    ) -> None:
        dbg(
            build_music_play_command_debug_message(
                url=url,
                guild_id=interaction.guild.id,
                user_id=interaction.user.id,
            )
        )
        await self._dispatch_music_play_command_branch(
            interaction,
            url,
            skip_defer=skip_defer,
        )
