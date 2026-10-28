from __future__ import annotations

import asyncio
import time
import discord
from util.music.state import reset_music_idle_state, reset_music_playback_state
from util.music.playback import MusicPlayerPreparationError, prepare_music_player
from util.music.playback_actions import (
    begin_seek_playback_action,
    begin_stop_playback_action,
    complete_seek_playback_action,
    fail_seek_playback_action,
    pause_playback_action,
    resume_playback_action,
    skip_playback_action,
    toggle_loop_action,
    validate_seek_playback_action,
)
from util.music.source import YTDLSource
from util.music.voice import same_voice_channel_error
from util.music.chapters import music_chapters, current_chapter_index
from .runtime import MSG_NO_PLAYING, dbg, logger


class MusicControlsMixin:
    async def _pause(self, interaction):
        # !기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            guild_id = interaction.guild.id
            state = self._get_state(guild_id)
            voice_client = interaction.guild.voice_client
            # !재생중 아님
            if not voice_client or not voice_client.is_playing():
                await self._send_auto_delete(interaction, MSG_NO_PLAYING)
                return
            if error := same_voice_channel_error(interaction, voice_client):
                await self._send_auto_delete(interaction, error)
                return
            logger.debug("음악 일시정지 요청: guild_id=%s", guild_id)
            voice_client.pause()
            result = pause_playback_action(state, paused_at=time.time())
            # ! embed 업데이트
            embed = self._make_playing_embed(state.player, guild_id, result.elapsed)
            # ! view 재생성
            state.control_view = await self._build_control_view(guild_id, state)
            await self._edit_msg(state, embed, state.control_view)
            # !메시지
            await self._send_auto_delete(interaction, result.user_message)

    async def _resume(self, interaction):
        # !기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            guild_id = interaction.guild.id
            state = self._get_state(guild_id)
            voice_client = interaction.guild.voice_client
            try:
                # !재생중 아님
                if not voice_client or not voice_client.is_paused():
                    await self._send_auto_delete(interaction, "❌ 일시정지된 음악이 없습니다.")
                    return
                if error := same_voice_channel_error(interaction, voice_client):
                    await self._send_auto_delete(interaction, error)
                    return
                logger.debug("음악 다시 재생 요청: guild_id=%s", guild_id)
                voice_client.resume()
                result = resume_playback_action(state, resumed_at=time.time())
                # ! embed 업데이트
                embed = self._make_playing_embed(state.player, guild_id, result.elapsed)
                # ! view 재생성
                state.control_view = await self._build_control_view(guild_id, state)
                await self._edit_msg(state, embed, state.control_view)
                # !메시지
                await self._send_auto_delete(interaction, result.user_message)
            except (
                discord.ClientException,
                discord.HTTPException,
                AttributeError,
                TypeError,
                ValueError,
            ):
                logger.warning("음악 다시 재생 실패: guild_id=%s", guild_id, exc_info=True)
                await self._send_auto_delete(
                    interaction, "❌ 다시 재생 중 오류가 발생했습니다."
                )

    async def _skip(self, interaction: discord.Interaction):
        # ! 기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            guild_id = interaction.guild.id
            logger.debug("음악 스킵 요청: guild_id=%s", guild_id)
            state = self._get_state(guild_id)
            voice_client = interaction.guild.voice_client
            if not voice_client or not voice_client.is_playing():
                await self._send_auto_delete(interaction, MSG_NO_PLAYING)
                return
            if error := same_voice_channel_error(interaction, voice_client):
                await self._send_auto_delete(interaction, error)
                return

            result = skip_playback_action(state)
            voice_client.stop()

            # !메시지
            await self._send_auto_delete(interaction, result.user_message)

    async def _stop(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            logger.debug("음악 정지 요청: guild_id=%s", interaction.guild.id)
            state = self._get_state(interaction.guild.id)
            voice_client = interaction.guild.voice_client
            if not voice_client:
                await self._send_auto_delete(interaction, "❌ 봇이 음성채널에 없습니다.")
                return
            if error := same_voice_channel_error(interaction, voice_client):
                await self._send_auto_delete(interaction, error)
                return
            # 정지 상태 진입
            state.playback_generation += 1
            self._cancel_idle_disconnect(state)
            result = begin_stop_playback_action(state)
            try:
                voice_client.stop()
                await voice_client.disconnect()
            finally:
                reset_music_playback_state(state)
                reset_music_idle_state(state)
                state.is_seeking = False

            # ! reset panel
            state.control_view = await self._build_helper_view(interaction.guild.id)
            embed = self._make_default_embed()
            await self._edit_msg(state, embed, state.control_view)

            # ! 메시지
            await self._send_auto_delete(interaction, result.user_message)

    async def _seek_chapter(self, interaction: discord.Interaction, direction: int, expected_player):
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            state = self._get_state(interaction.guild.id)
            if state.player is None or state.player is not expected_player:
                await self._send_auto_delete(interaction, "❌ 곡이 변경되었습니다. 현재 음악 패널에서 다시 선택해주세요.")
                return
            chapters = music_chapters(state.player.data)
            now = state.paused_at if state.paused_at is not None else time.time()
            elapsed = max(0, now - state.start_ts) if state.start_ts else 0
            target = current_chapter_index(chapters, elapsed) + direction
            if not 0 <= target < len(chapters):
                await self._send_auto_delete(interaction, "❌ 이동할 챕터가 없습니다.")
                return
            await self._seek(interaction, chapters[target].start_time)

    async def _seek(self, interaction: discord.Interaction, seconds: int):
        dbg(f"_seek: seconds={seconds}")
        # ! 기본정보 로드
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._music_operation(interaction.guild.id):
            guild_id = interaction.guild.id
            state = self._get_state(guild_id)
            voice_client = interaction.guild.voice_client
            if not voice_client or not state.player:
                # ! 메시지
                await self._send_auto_delete(interaction, MSG_NO_PLAYING)
                return
            if error := same_voice_channel_error(interaction, voice_client):
                await self._send_auto_delete(interaction, error)
                return
            player = None
            restart_started = False
            was_paused = state.paused_at is not None
            try:
                validation_result = validate_seek_playback_action(state, seconds=seconds)
                if validation_result:
                    await self._send_auto_delete(
                        interaction,
                        validation_result.user_message,
                        delay=validation_result.delete_after,
                    )
                    return
                # ! 새로운 player 생성 (start_time 포함)
                previous_player = state.player
                player = await prepare_music_player(
                    YTDLSource.from_url,
                    state.player.webpage_url,
                    loop=self.bot.loop,
                    start_time=seconds,
                    requester=state.player.requester,
                )
                if not player.data.get("chapters") and previous_player.data.get("chapters"):
                    player.data["chapters"] = previous_player.data["chapters"]
                # ! 멈추고 재생 위치부터 새 소스 생성
                restart_started = True
                begin_seek_playback_action(state)
                state.playback_generation += 1
                voice_client.stop()
                dbg("_seek: stopped current and will restart from position")
                result = complete_seek_playback_action(
                    state,
                    player,
                    seconds=seconds,
                    started_at=time.time(),
                )
                # ! play & updater 재시작
                self._vc_play(guild_id=guild_id, source=player.source)
                if was_paused:
                    voice_client.pause()
                    state.paused_at = time.time()
                await self._restart_updater(guild_id)
                # ! 메시지 수정(임베드, 뷰)
                embed = self._make_playing_embed(
                    state.player,
                    guild_id,
                    elapsed=result.elapsed,
                )
                state.control_view = await self._build_control_view(guild_id, state)
                await self._edit_msg(state, embed, state.control_view)
                # ! 메시지
                await self._send_auto_delete(interaction, result.user_message)
            except asyncio.CancelledError:
                if player is not None:
                    self._abort_prepared_playback(guild_id, state, player.source)
                raise
            except MusicPlayerPreparationError as exc:
                result = fail_seek_playback_action(state)
                if isinstance(exc.original_error, FileNotFoundError):
                    await self._send_auto_delete(
                        interaction,
                        exc.failure.user_message,
                        delay=exc.failure.delete_after,
                    )
                    return
                dbg(f"_seek: {exc.failure.debug_message}")
                await self._send_auto_delete(
                    interaction,
                    result.user_message,
                    delay=result.delete_after,
                )
            except (
                discord.ClientException,
                discord.HTTPException,
                AttributeError,
                TypeError,
                ValueError,
            ):
                logger.warning(
                    "음악 구간 이동 실패: guild_id=%s seconds=%s",
                    guild_id,
                    seconds,
                    exc_info=True,
                )
                if player is not None and restart_started:
                    self._abort_prepared_playback(guild_id, state, player.source)
                # 실패 시 is_seeking 안전 복구
                result = fail_seek_playback_action(state)
                await self._send_auto_delete(
                    interaction,
                    result.user_message,
                    delay=result.delete_after,
                )

    async def _toggle_loop(self, interaction: discord.Interaction):
        """🔁 반복 모드 토글"""
        await interaction.response.defer(thinking=True, ephemeral=True)
        # ! 상태 업데이트
        async with self._music_operation(interaction.guild.id):
            state = self._get_state(interaction.guild.id)
            voice_client = interaction.guild.voice_client
            if voice_client and (error := same_voice_channel_error(interaction, voice_client)):
                await self._send_auto_delete(interaction, error)
                return
            result = toggle_loop_action(state)
            # ! 메시지
            await self._send_auto_delete(interaction, result.user_message)
