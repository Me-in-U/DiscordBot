from __future__ import annotations

import discord
from discord import Embed
from util.music.embeds import UNKNOWN
from util.music.queue import QueuedTrack, build_queue_display, fill_queue_track_metadata
from util.music.queue_actions import (
    begin_search_pick_queue_action,
    clear_queue_action,
    move_queue_action,
    remove_queue_action,
    shuffle_queue_action,
)
from util.music.search import MusicSearchActionResult, build_music_search_flow
from util.music.source import YTDL_EXECUTOR, info_ytdl, search_ytdl
from util.music.views import SearchResultView
from util.music.voice import same_voice_channel_error
from .runtime import MAX_QUEUE_DISPLAY, logger


class MusicQueueMixin:
    async def _send_music_search_response(
        self,
        interaction: discord.Interaction,
        search_result: MusicSearchActionResult,
        *,
        favorite_slot: int | None = None,
    ) -> None:
        if search_result.user_message:
            await self._send_ephemeral_response(
                interaction,
                search_result.user_message,
            )
            return

        embed = Embed(
            title=search_result.embed_title,
            description=search_result.embed_description,
            color=0xFFC0CB,
        )
        view = SearchResultView(
            self,
            search_result.videos,
            favorite_slot=favorite_slot,
        )
        await self._send_ephemeral_response(interaction, embed=embed, view=view)

    async def _play_music_search_branch(
        self,
        interaction: discord.Interaction,
        query: str,
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)
        search_result = await build_music_search_flow(
            query,
            search_ytdl,
            executor=YTDL_EXECUTOR,
        )
        await self._send_music_search_response(interaction, search_result)

    async def _fill_queue_meta(self, track: "QueuedTrack"):
        """대기열 트랙의 가벼운 메타데이터를 채운다(재생에 영향 없음)."""
        try:
            await fill_queue_track_metadata(
                track,
                lambda url: info_ytdl.extract_info(url, download=False),
                executor=YTDL_EXECUTOR,
            )
        except (RuntimeError, TypeError, ValueError, KeyError):
            logger.debug("대기열 메타데이터 반영 실패: url=%s", track.url, exc_info=True)

    async def _play_from_search_pick(
        self, interaction: discord.Interaction, entry: dict
    ):
        """검색 버튼 선택 시, 가능한 메타를 최대한 채워서 바로 재생/대기열 추가"""
        async with self._music_operation(interaction.guild.id):
            voice_client = interaction.guild.voice_client
            state = self._get_state(interaction.guild.id)
            is_active = bool(
                voice_client and (voice_client.is_playing() or voice_client.is_paused())
            )
            if is_active:
                error = same_voice_channel_error(interaction, voice_client)
                if error:
                    await self._send_auto_delete(interaction, error)
                    return

            search_pick_result = begin_search_pick_queue_action(
                state.queue,
                entry,
                requester=interaction.user,
                is_active=is_active,
            )
            if not search_pick_result.should_play_now:
                if search_pick_result.queued_track is not None:
                    self._spawn_bg(self._fill_queue_meta(search_pick_result.queued_track))
                await self._send_auto_delete(
                    interaction,
                    search_pick_result.user_message,
                )
                return

            await self._play(interaction, search_pick_result.url, skip_defer=True)

    async def _show_queue(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        logger.debug("음악 대기열 보기 요청: guild_id=%s", interaction.guild.id)
        state = self._get_state(interaction.guild.id)
        if not state.queue:
            await self._send_auto_delete(interaction, "❌ 대기열이 비어있습니다.")
            return

        display = build_queue_display(
            state.queue,
            player=state.player,
            max_display=MAX_QUEUE_DISPLAY,
            unknown=UNKNOWN,
        )

        embed = Embed(
            title=display.title,
            description=display.description,
            color=0xFFC0CB,
        )

        await self._send_auto_delete(interaction, embed=embed, delay=20.0)

    async def _remove_from_queue(
        self, interaction: discord.Interaction, position: int
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            voice_client = interaction.guild.voice_client
            if voice_client and (error := same_voice_channel_error(interaction, voice_client)):
                await self._send_auto_delete(interaction, error)
                return

            state = self._get_state(interaction.guild.id)
            try:
                result = remove_queue_action(state.queue, position)
            except ValueError as e:
                await self._send_auto_delete(interaction, f"❌ {e}")
                return
            await self._send_auto_delete(interaction, result.user_message)

    async def _clear_queue(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            voice_client = interaction.guild.voice_client
            if voice_client and (error := same_voice_channel_error(interaction, voice_client)):
                await self._send_auto_delete(interaction, error)
                return

            state = self._get_state(interaction.guild.id)
            try:
                result = clear_queue_action(state.queue)
            except ValueError as e:
                await self._send_auto_delete(interaction, f"❌ {e}")
                return
            await self._send_auto_delete(interaction, result.user_message)

    async def _move_queue(
        self, interaction: discord.Interaction, current_position: int, new_position: int
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            voice_client = interaction.guild.voice_client
            if voice_client and (error := same_voice_channel_error(interaction, voice_client)):
                await self._send_auto_delete(interaction, error)
                return

            state = self._get_state(interaction.guild.id)
            try:
                result = move_queue_action(state.queue, current_position, new_position)
            except ValueError as e:
                await self._send_auto_delete(interaction, f"❌ {e}")
                return
            await self._send_auto_delete(interaction, result.user_message)

    async def _shuffle_queue(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            voice_client = interaction.guild.voice_client
            if voice_client and (error := same_voice_channel_error(interaction, voice_client)):
                await self._send_auto_delete(interaction, error)
                return

            state = self._get_state(interaction.guild.id)
            try:
                result = shuffle_queue_action(state.queue)
            except ValueError as e:
                await self._send_auto_delete(interaction, f"❌ {e}")
                return
            await self._send_auto_delete(interaction, result.user_message)
