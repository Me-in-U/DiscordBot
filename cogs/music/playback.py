from __future__ import annotations

import asyncio
import time
from typing import Any
import discord
from util.music.state import (
    GuildMusicState,
    finish_music_track_state,
    reset_music_idle_state,
    reset_music_playback_state,
    start_music_playback_state,
)
from util.music.playback import (
    MusicPlayerPreparationError,
    prepare_music_player,
    prepare_replay_source,
)
from util.music.source import YTDLSource, _detect_ffmpeg_executable, ffmpeg_options
from .runtime import IDLE_DISCONNECT_SECONDS, dbg, logger


class MusicPlaybackMixin:
    async def _disconnect_voice_client_safely(
        self,
        voice_client: Any,
        *,
        action: str,
    ) -> None:
        try:
            await voice_client.disconnect()
        except (discord.ClientException, asyncio.TimeoutError, OSError):
            logger.debug("%s: 음성 연결 해제 실패", action, exc_info=True)

    async def _start_prepared_playback(
        self,
        *,
        guild_id: int,
        state: GuildMusicState,
        player: Any,
        playback_start: Any,
        started_at: float | None = None,
    ) -> None:
        self._cancel_idle_disconnect(state)
        start_music_playback_state(
            state,
            player,
            started_at=time.time() if started_at is None else started_at,
        )
        state.control_view = await self._build_control_view(guild_id, state)
        self._vc_play(guild_id=guild_id, source=playback_start.source)
        await self._restart_updater(guild_id)
        embed = self._make_playing_embed(player, guild_id)
        await self._edit_msg(state=state, embed=embed, view=state.control_view)

    async def _updater_loop(self, guild_id: int):
        state = self._get_state(guild_id)
        try:
            dbg("_updater_loop: start")
            while state.player:
                guild = self.bot.get_guild(guild_id)
                voice_client = guild.voice_client if guild else None
                # ! voice_client 연결 끊김
                if not voice_client:
                    dbg("_updater_loop: voice_client disconnected")
                    await self._force_stop(guild_id)
                    return
                # ! 봇만 남아있음 → 종료 호출
                if voice_client and len(voice_client.channel.members) == 1:
                    dbg("_updater_loop: bot alone in channel, stopping")
                    await self._force_stop(guild_id)
                    return
                # ! 일시정지 대기
                if voice_client.is_paused():
                    dbg("_updater_loop: paused")
                    await asyncio.sleep(1)
                    continue
                # ! 재생시간 계산
                elapsed = int(time.time() - state.start_ts)
                total = state.player.data.get("duration", 0)
                dbg(f"_updater_loop: elapsed={elapsed} total={total}")
                # ! 메시지 수정(임베드, 뷰)
                embed = self._make_playing_embed(
                    state.player, guild_id, min(elapsed, total) if total else elapsed
                )
                await self._edit_msg(state, embed, state.control_view)
                await asyncio.sleep(5)
        finally:
            dbg("_updater_loop: end")
            if state.updater_task is asyncio.current_task():
                state.updater_task = None

    def _cancel_idle_disconnect(self, state: GuildMusicState) -> None:
        task = state.idle_disconnect_task
        if task and not task.done():
            task.cancel()
        state.idle_disconnect_task = None

    def _schedule_idle_disconnect(self, guild_id: int) -> None:
        state = self._get_state(guild_id)
        self._cancel_idle_disconnect(state)
        task = self._spawn_bg(self._idle_disconnect_after_timeout(guild_id))
        state.idle_disconnect_task = task

        def _clear_task(done_task: asyncio.Task) -> None:
            if state.idle_disconnect_task is done_task:
                state.idle_disconnect_task = None

        task.add_done_callback(_clear_task)

    async def _idle_disconnect_after_timeout(self, guild_id: int):
        try:
            await asyncio.sleep(IDLE_DISCONNECT_SECONDS)
            async with self._music_operation(guild_id):
                state = self._get_state(guild_id)
                if state.player or state.queue:
                    return

                guild = self.bot.get_guild(guild_id)
                voice_client = guild.voice_client if guild else None
                if voice_client:
                    await self._disconnect_voice_client_safely(
                        voice_client,
                        action="_idle_disconnect_after_timeout",
                    )

                state.control_view = await self._build_helper_view(guild_id)
                reset_music_idle_state(state)
                await self._edit_music_panel_safely(
                    state,
                    self._make_default_embed(),
                    state.control_view,
                    action="_idle_disconnect_after_timeout",
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("음악 idle disconnect 처리 실패: guild_id=%s", guild_id)

    async def _force_stop(self, guild_id: int):
        """interaction 없이 강제 정지하고 패널을 초기 상태로 돌립니다."""
        dbg(f"_force_stop: guild_id={guild_id}")
        async with self._music_operation(guild_id):
            state = self._get_state(guild_id)
            self._cancel_idle_disconnect(state)
            guild = self.bot.get_guild(guild_id)
            vc = guild.voice_client if guild else None
            # 정지 상태 진입
            state.playback_generation += 1
            state.is_stopping = True
            if vc:
                await self._disconnect_voice_client_safely(
                    vc,
                    action="_force_stop",
                )
            state.control_view = await self._build_helper_view(guild_id)
            embed = self._make_default_embed()
            await self._edit_music_panel_safely(
                state,
                embed,
                state.control_view,
                action="_force_stop",
            )
            # 상태 초기화
            reset_music_playback_state(state)

    async def _restart_updater(self, guild_id: int):
        dbg("_restart_updater: called")
        # ! 기본정보 로드
        state = self._get_state(guild_id)

        previous_task = state.updater_task
        if previous_task and previous_task is not asyncio.current_task():
            previous_task.cancel()
            await asyncio.gather(previous_task, return_exceptions=True)
        state.updater_task = self._spawn_bg(self._updater_loop(guild_id))

    def _vc_play(
        self, guild_id: int = None, interaction: discord.Interaction = None, source=None
    ):
        guild_id = guild_id if guild_id is not None else interaction.guild.id
        state = self._get_state(guild_id)
        state.playback_generation += 1
        generation = state.playback_generation
        # ! 재생 및 다음 곡 콜백 등록
        def _after_play(error):
            if error:
                dbg(f"_after_play: error={error}")
            else:
                dbg("_after_play: finished")

            def _schedule_song_end() -> None:
                self._spawn_bg(self._on_song_end(guild_id, generation=generation))

            self.bot.loop.call_soon_threadsafe(_schedule_song_end)

        # ! voice_client 가져오기
        if guild_id:
            guild = self.bot.get_guild(guild_id)
            voice_client = guild.voice_client
        else:
            voice_client = interaction.guild.voice_client

        # ! 재생
        try:
            dbg("_vc_play: voice_client.play invoked")
            voice_client.play(source, after=_after_play)
        except discord.errors.ClientException:
            dbg("_vc_play: ClientException -> stop then play")
            voice_client.stop()
            voice_client.play(source, after=_after_play)

    async def _on_song_end(self, guild_id: int, *, generation: int | None = None):
        dbg("_on_song_end: called")
        # ! 기본정보 로드
        async with self._music_operation(guild_id):
            state = self._get_state(guild_id)
            if generation is not None and generation != state.playback_generation:
                return
            # 한 재생의 종료는 한 번만 처리한다.
            state.playback_generation += 1

            # 정지 상태면 아무 것도 하지 않음
            if state.is_stopping:
                dbg("_on_song_end: stopping flag set -> return")
                state.is_stopping = False
                return

            # ! seek 발생시 종료 로직 무시
            if state.is_seeking:
                dbg("_on_song_end: in seeking, ignore")
                return

            finish_music_track_state(state, ended_at=time.time())

            # !루프이거나 루프상태인데 스킵하면 처음부터
            if state.is_skipping or state.is_loop:
                dbg(f"_on_song_end: loop/skip replay queue_size={len(state.queue)}")
                try:
                    replay = await prepare_replay_source(
                        state.player,
                        source_factory=YTDLSource.from_url,
                        ffmpeg_source_factory=discord.FFmpegOpusAudio,
                        ffmpeg_options=ffmpeg_options,
                        ffmpeg_executable=_detect_ffmpeg_executable(),
                        loop=self.bot.loop,
                    )
                except MusicPlayerPreparationError:
                    logger.warning(
                        "음악 반복 재생 소스 준비 실패: guild_id=%s",
                        guild_id,
                        exc_info=True,
                    )
                    await self._force_stop(guild_id)
                    return
                # ! 상태 업데이트
                if replay.refreshed_player is not None:
                    state.player.audio_url = replay.refreshed_player.audio_url
                state.player.source = replay.source
                # ! play & updater 재시작
                self._vc_play(guild_id, source=replay.source)
                await self._restart_updater(guild_id)
                return

            # !대기열에 곡이 없으면 패널을 빈(embed 초기) 상태로 리셋
            if not state.queue:
                dbg("_on_song_end: no next track -> reset panel and wait for idle timeout")
                reset_music_idle_state(state)
                state.control_view = await self._build_helper_view(guild_id)
                await self._edit_msg(state, self._make_default_embed(), state.control_view)
                self._schedule_idle_disconnect(guild_id)
                return

            # ! 다음 곡 준비: URL -> YTDLSource 변환 후 재생
            dbg(f"_on_song_end: next track popped, queue_size={len(state.queue)}")
            track = state.queue.popleft()
            try:
                player = await prepare_music_player(
                    YTDLSource.from_url,
                    track.url,
                    loop=self.bot.loop,
                    requester=track.requester,
                )
            except MusicPlayerPreparationError as exc:
                dbg(f"_on_song_end: next track prepare failed: {exc.failure.debug_message}")
                # 실패 시 다음 곡으로 넘어가기 시도 (재귀적 호출 방지 위해 task로)
                self._spawn_bg(self._on_song_end(guild_id, generation=state.playback_generation))
                return
            self._cancel_idle_disconnect(state)
            start_music_playback_state(state, player, started_at=time.time())
            embed = self._make_playing_embed(state.player, guild_id)
            await self._edit_msg(state, embed, state.control_view)
            self._vc_play(guild_id, source=state.player.source)
            await self._restart_updater(guild_id)
