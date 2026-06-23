# cogs/music.py
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Tuple, Coroutine, Any

import aiomysql
import discord
from discord import Embed, Message, Object, TextChannel, app_commands
from discord.ext import commands
from discord.utils import utcnow
from yt_dlp.utils import DownloadError
from util.channel_settings import get_channel
from util.music_favorites import (
    MusicFavorite,
    MusicFavoriteSavePayload,
    build_music_favorite_current_track_save_action,
    build_music_favorite_manager_open_action,
    build_music_favorite_play_action,
    build_music_favorite_search_request_action,
    current_player_to_music_favorite,
    get_music_favorite,
    list_music_favorites,
    search_entry_to_music_favorite_save_payload,
    upsert_music_favorite,
)
from util.music_embeds import (
    PANEL_TITLE,
    UNKNOWN,
    make_default_music_embed,
    make_playing_music_embed,
)
from util.music_queue import (
    QueuedTrack,
    build_queue_display,
    _track_title,
    build_queue_preview,
    move_queue_track,
    parse_seek_seconds,
    remove_queue_track,
    shuffle_queue,
)
from util.music_queue_actions import (
    begin_search_pick_queue_action,
    clear_queue_action,
    move_queue_action,
    remove_queue_action,
    shuffle_queue_action,
)
from util.music_state import (
    GuildMusicState,
    finish_music_track_state,
    reset_music_idle_state,
    reset_music_playback_state,
    start_music_playback_state,
)
from util.music_progress import (
    make_progress_bar as build_music_progress_bar,
    make_timeline_line as build_music_timeline_line,
)
from util.music_search import (
    build_music_search_action,
    is_http_url,
)
from util.music_panel_store import (
    delete_music_panel_id,
    load_music_panel_ids,
    save_music_panel_id,
)
from util.music_playback import (
    MusicPlayerPreparationError,
    build_prepared_playback_start,
    prepare_music_player,
    prepare_replay_source,
)
from util.music_playback_actions import (
    begin_seek_playback_action,
    begin_stop_playback_action,
    begin_url_play_action,
    complete_seek_playback_action,
    fail_seek_playback_action,
    pause_playback_action,
    resume_playback_action,
    skip_playback_action,
    toggle_loop_action,
    validate_seek_playback_action,
)
from util.music_source import (
    YTDL_EXECUTOR,
    YTDLSource,
    _detect_ffmpeg_executable,
    ffmpeg_options,
    info_ytdl,
    search_ytdl,
)
from util.music_views import (
    FavoriteSearchModal,
    MusicControlView,
    MusicFavoriteManageView,
    MusicHelperView,
    SearchResultView,
)
from util.music_voice import (
    describe_voice_transition,
    ensure_music_voice_client,
    get_interaction_voice_channel,
    is_voice_client_active,
    same_voice_channel_error,
)
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
# 공통 상수
DEFAULT_MUSIC_CHANNEL_NAME = "🎵ㆍ神-음악채널"
MUSIC_CHANNEL_TYPE = "music"
MAX_QUEUE_DISPLAY = 10
IDLE_DISCONNECT_SECONDS = 300
MSG_NO_PLAYING = "❌ 재생 중인 음악이 없습니다."
# 간단한 디버그 로깅 헬퍼
def dbg(msg: str):
    try:
        logger.debug("[MUSIC] %s", msg)
    except (OSError, RuntimeError):
        logger.debug("music debug 출력 실패", exc_info=True)


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}  # 길드별 상태 저장
        # 백그라운드 태스크 레퍼런스 보관(조기 GC 방지)
        self._bg_tasks: set[asyncio.Task] = set()
        # 패널 메시지 ID 저장 로드
        self._panel_ids: dict[str, int] = {}
        # 음악 채널 일반 채팅 자동삭제 경고 쿨다운 관리
        self._last_warn: dict[int, float] = {}
        self._warn_cooldown = 10.0  # 초
        # 부팅시 1회 정리 수행 여부
        self._purged_guilds: set[int] = set()
        self._favorite_cache: dict[int, list[MusicFavorite]] = {}

    # === 패널 ID 저장/로드 유틸 ===
    async def cog_load(self):
        self._panel_ids = await self._load_panel_ids()

    async def _load_panel_ids(self) -> dict[str, int]:
        try:
            return await load_music_panel_ids()
        except (aiomysql.Error, TypeError, ValueError, KeyError):
            logger.warning("패널 ID DB 로드 실패", exc_info=True)
            return {}

    async def _set_panel_id(self, guild_id, message_id):
        await save_music_panel_id(self._panel_ids, guild_id, message_id)

    async def _del_panel_id(self, guild_id):
        await delete_music_panel_id(self._panel_ids, guild_id)

    def _spawn_bg(self, coro: "Coroutine[Any, Any, Any]") -> asyncio.Task:
        """백그라운드 태스크를 등록하고 레퍼런스를 보관한다."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)

        def _log_and_discard(done_task: asyncio.Task) -> None:
            self._bg_tasks.discard(done_task)
            try:
                exception = done_task.exception()
            except asyncio.CancelledError:
                return
            if exception is not None:
                logger.exception(
                    "music background task failed",
                    exc_info=(type(exception), exception, exception.__traceback__),
                )

        task.add_done_callback(_log_and_discard)
        return task

    async def _load_music_favorites(
        self,
        guild_id: int,
        *,
        refresh: bool = False,
    ) -> list[MusicFavorite]:
        if not refresh and guild_id in self._favorite_cache:
            return self._favorite_cache[guild_id]
        try:
            favorites = await list_music_favorites(guild_id)
        except (aiomysql.Error, TypeError, ValueError, KeyError):
            logger.warning("음악 즐겨찾기 로드 실패: guild_id=%s", guild_id, exc_info=True)
            favorites = []
        self._favorite_cache[guild_id] = favorites
        return favorites

    async def _build_helper_view(self, guild_id: int) -> MusicHelperView:
        favorites = await self._load_music_favorites(guild_id)
        return MusicHelperView(self, favorites)

    async def _build_control_view(
        self,
        guild_id: int,
        state: GuildMusicState,
    ) -> MusicControlView:
        favorites = await self._load_music_favorites(guild_id)
        return MusicControlView(self, state, favorites)

    def _current_player_as_favorite(
        self,
        guild_id: int,
        player: Optional["YTDLSource"],
    ) -> MusicFavorite | None:
        return current_player_to_music_favorite(guild_id, player)

    async def _fill_queue_meta(self, track: "QueuedTrack"):
        """대기열 트랙의 가벼운 메타데이터를 채운다(재생에 영향 없음)."""
        try:
            loop = asyncio.get_event_loop()

            def _extract():
                try:
                    return info_ytdl.extract_info(track.url, download=False)
                except (DownloadError, OSError, TypeError, ValueError):
                    logger.debug("대기열 메타데이터 추출 실패: url=%s", track.url, exc_info=True)
                    return None

            info = await loop.run_in_executor(YTDL_EXECUTOR, _extract)
            if not info or not isinstance(info, dict):
                return
            # 단일 엔트리 처리
            if "entries" in info and info.get("entries"):
                entry = (info.get("entries") or [None])[0]
                if isinstance(entry, dict):
                    info = entry
            track.title = info.get("title") or track.title
            track.duration = int(info.get("duration") or 0) or track.duration
            track.webpage_url = (
                info.get("webpage_url") or track.webpage_url or track.url
            )
            track.uploader = info.get("uploader") or track.uploader
            # 썸네일은 여러 키가 있을 수 있음
            thumbnails = info.get("thumbnails")
            thumbnail_url = None
            if isinstance(thumbnails, list) and thumbnails:
                last_thumbnail = thumbnails[-1]
                if isinstance(last_thumbnail, dict):
                    thumbnail_url = last_thumbnail.get("url")
            track.thumbnail = (
                info.get("thumbnail")
                or thumbnail_url
                or track.thumbnail
            )
        except (RuntimeError, TypeError, ValueError, KeyError):
            logger.debug("대기열 메타데이터 반영 실패: url=%s", track.url, exc_info=True)

    async def _open_music_favorite_manager(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        favorites = await self._load_music_favorites(guild_id, refresh=True)
        state = self._get_state(guild_id)
        manager_action = build_music_favorite_manager_open_action(
            guild_id=guild_id,
            favorites=favorites,
            player=state.player,
        )
        view = MusicFavoriteManageView(
            self,
            guild_id=manager_action.guild_id,
            favorites=manager_action.favorites,
            current_track=manager_action.current_track,
        )
        await self._send_ephemeral_response(
            interaction,
            manager_action.status_text,
            view=view,
        )

    async def _search_music_for_favorite_slot(
        self,
        interaction: discord.Interaction,
        slot: int,
        query: str,
    ) -> None:
        favorite_search_action = build_music_favorite_search_request_action(
            slot=slot,
            query_value=query,
        )
        if favorite_search_action.user_message:
            await self._send_ephemeral_response(
                interaction,
                favorite_search_action.user_message,
            )
            return

        info = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: search_ytdl.extract_info(
                f"ytsearch10:{favorite_search_action.query}",
                download=False,
            ),
        )
        search_result = build_music_search_action(
            query=favorite_search_action.query,
            info=info,
            favorite_slot=favorite_search_action.slot,
        )
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
            favorite_slot=favorite_search_action.slot,
        )
        await self._send_ephemeral_response(interaction, embed=embed, view=view)

    async def _save_music_favorite(
        self,
        interaction: discord.Interaction,
        payload: MusicFavoriteSavePayload,
    ) -> None:
        await upsert_music_favorite(
            guild_id=payload.guild_id,
            slot=payload.slot,
            title=payload.title,
            url=payload.url,
            duration=payload.duration,
            uploader=payload.uploader,
            thumbnail=payload.thumbnail,
            updated_by=payload.updated_by,
        )
        await self._load_music_favorites(payload.guild_id, refresh=True)
        await self._refresh_music_panel_for_favorites(payload.guild_id)
        await self._send_auto_delete(
            interaction,
            payload.user_message,
        )

    async def _save_search_entry_as_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
        entry: dict,
    ) -> None:
        payload = search_entry_to_music_favorite_save_payload(
            guild_id=interaction.guild.id,
            slot=slot,
            entry=entry,
            updated_by=interaction.user.id,
        )
        await self._save_music_favorite(
            interaction,
            payload,
        )

    async def _save_current_track_as_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        favorite = self._current_player_as_favorite(guild_id, state.player)
        current_action = build_music_favorite_current_track_save_action(
            current_track=favorite,
            slot=slot,
            updated_by=interaction.user.id,
        )
        if current_action.user_message:
            await self._send_auto_delete(
                interaction,
                current_action.user_message,
            )
            return
        if current_action.payload is None:
            return
        await self._save_music_favorite(
            interaction,
            current_action.payload,
        )

    async def _refresh_music_panel_for_favorites(self, guild_id: int) -> None:
        state = self._get_state(guild_id)
        if state.control_msg is None or state.control_channel is None:
            return
        if state.player:
            state.control_view = await self._build_control_view(guild_id, state)
            elapsed = int(time.time() - state.start_ts) if state.start_ts else 0
            embed = self._make_playing_embed(state.player, guild_id, elapsed)
        else:
            state.control_view = await self._build_helper_view(guild_id)
            embed = self._make_default_embed()
        await self._edit_msg(state, embed, state.control_view)

    async def _play_music_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
    ) -> None:
        slot = build_music_favorite_play_action(slot=slot, favorite=None).slot
        favorite = await get_music_favorite(interaction.guild.id, slot)
        play_result = build_music_favorite_play_action(slot=slot, favorite=favorite)
        if not play_result.should_play:
            await self._send_ephemeral_response(
                interaction,
                play_result.user_message,
            )
            return
        await self._play_url_now(
            interaction,
            play_result.url,
            success_prefix=play_result.success_prefix,
        )

    async def _play_from_search_pick(
        self, interaction: discord.Interaction, entry: dict
    ):
        """검색 버튼 선택 시, 가능한 메타를 최대한 채워서 바로 재생/대기열 추가"""
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

    # !길드의 State 리턴
    def _get_state(self, guild_id: int) -> GuildMusicState:
        return self.states.setdefault(guild_id, GuildMusicState())

    async def _send_auto_delete(
        self,
        interaction: discord.Interaction,
        content: str | None = None,
        *,
        embed: Embed | None = None,
        delay: float = 5.0,
    ) -> None:
        msg = await interaction.followup.send(
            content,
            embed=embed,
            ephemeral=True,
        )
        self._spawn_bg(self._auto_delete(msg, delay))

    async def _send_ephemeral_response(
        self,
        interaction: discord.Interaction,
        content: str | None = None,
        *,
        embed: Embed | None = None,
        view: Any | None = None,
    ) -> None:
        try:
            response_is_done = getattr(interaction.response, "is_done", None)
            response_done = (
                response_is_done()
                if callable(response_is_done)
                else bool(getattr(interaction.response, "deferred", False))
            )
            if not response_done:
                await interaction.response.send_message(
                    content,
                    embed=embed,
                    view=view,
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    content,
                    embed=embed,
                    view=view,
                    ephemeral=True,
                )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.warning("음악 ephemeral 응답 전송 실패", exc_info=True)

    async def _send_channel_auto_delete(
        self,
        channel: Any,
        content: str,
        *,
        delay: float = 5.0,
    ) -> None:
        try:
            sent_message = await channel.send(content)
            self._spawn_bg(self._auto_delete(sent_message, delay))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("음악 채널 자동삭제 메시지 전송 실패", exc_info=True)

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

    async def _edit_music_panel_safely(
        self,
        state: GuildMusicState,
        embed: Embed,
        view: Any,
        *,
        action: str,
    ) -> None:
        try:
            await self._edit_msg(state, embed, view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("%s: 음악 패널 업데이트 실패", action, exc_info=True)

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

    async def _resolve_music_channel(
        self, guild: discord.Guild
    ) -> Optional[TextChannel]:
        state = self._get_state(guild.id)
        configured_channel_id = await get_channel(guild.id, MUSIC_CHANNEL_TYPE)
        if configured_channel_id:
            configured = guild.get_channel(configured_channel_id)
            if isinstance(configured, TextChannel):
                return configured

        if isinstance(state.control_channel, TextChannel):
            return state.control_channel

        return discord.utils.get(guild.text_channels, name=DEFAULT_MUSIC_CHANNEL_NAME)

    async def _is_music_control_channel(self, message: discord.Message) -> bool:
        if not message.guild:
            return False

        state = self._get_state(message.guild.id)
        if state.control_channel and message.channel.id == state.control_channel.id:
            return True
        if message.channel.name == DEFAULT_MUSIC_CHANNEL_NAME:
            return True

        configured_channel_id = await get_channel(message.guild.id, MUSIC_CHANNEL_TYPE)
        return bool(configured_channel_id and message.channel.id == configured_channel_id)

    def make_timeline_line(self, elapsed: int, total: int, length: int = 16) -> str:
        return build_music_timeline_line(elapsed, total, length)

    def make_progress_bar(
        self, elapsed: int, total: int, length: int = 23
    ) -> Tuple[str, int]:
        return build_music_progress_bar(elapsed, total, length)

    # ?완
    # !메시지 수정(임베드, 뷰)
    async def _edit_msg(self, state, embed, view):
        # 기존 메시지 재사용. 존재하지 않거나 삭제된 경우만 새로 생성
        try:
            if state.control_msg is None:
                state.control_msg = await state.control_channel.send(
                    embed=embed, view=view
                )
                # 새로 만든 경우 저장
                if state.control_channel and state.control_channel.guild:
                    gid = str(state.control_channel.guild.id)
                    await self._set_panel_id(gid, state.control_msg.id)
                return
            await state.control_msg.edit(embed=embed, view=view)
        except discord.HTTPException as e:
            if getattr(e, "code", None) == 10008:  # Unknown Message
                logger.info("음악 패널 메시지가 사라져 새로 생성합니다.")
                state.control_msg = await state.control_channel.send(
                    embed=embed, view=view
                )
                if state.control_channel and state.control_channel.guild:
                    gid = str(state.control_channel.guild.id)
                    await self._set_panel_id(gid, state.control_msg.id)
            else:
                logger.warning("패널 업데이트 실패", exc_info=True)

    # ?완
    # ! 노래 재생 상황 업데이트 루프
    async def _updater_loop(self, guild_id: int):
        state = self._get_state(guild_id)
        try:
            dbg("_updater_loop: start")
            while state.player:
                voice_client = state.control_msg.guild.voice_client
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
        state = self._get_state(guild_id)
        self._cancel_idle_disconnect(state)
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client if guild else None
        # 정지 상태 진입
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

    # ?완
    # ! 메시지 자동 삭제
    async def _auto_delete(self, msg: discord.Message, delay: float = 5.0):
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except discord.HTTPException:
            pass

    # ?완
    # ! 기본 임베드
    def _make_default_embed(self) -> Embed:
        try:
            return make_default_music_embed(
                bot_avatar_url=self.bot.user.avatar.url,
            )
        except (AttributeError, TypeError, ValueError):
            logger.exception("기본 음악 패널 임베드 생성 실패")
            raise

    # ! 노래 재생시 임베드
    def _make_playing_embed(
        self, player: YTDLSource, guild_id: int, elapsed: int = 0
    ) -> Embed:
        try:
            state = self._get_state(guild_id)
            return make_playing_music_embed(
                player,
                queue=state.queue,
                is_loop=state.is_loop,
                is_paused=state.paused_at is not None,
                elapsed=elapsed,
                fallback_requester_icon_url=self.bot.user.avatar.url,
            )
        except (AttributeError, TypeError, ValueError):
            logger.exception("음악 재생 임베드 생성 실패")
            raise

    # ?완
    # ! 전용채널의 봇 댓글 가져오거나 생성
    async def _get_or_create_panel(self, guild: discord.Guild):
        # ! 상태 기본값 설정
        state = self._get_state(guild.id)
        # ! 채널 확보
        control_channel = await self._resolve_music_channel(guild)
        # ! 채널 없으면 생성
        if control_channel is None:
            logger.info("음악 채널이 없어 새로 생성합니다: guild_id=%s", guild.id)
            # ! 권한 설정
            bot_member = guild.get_member(self.bot.user.id)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(send_messages=True),
                bot_member: discord.PermissionOverwrite(
                    send_messages=True, embed_links=True, read_messages=True
                ),
            }
            control_channel = await guild.create_text_channel(
                DEFAULT_MUSIC_CHANNEL_NAME,
                overwrites=overwrites,
            )
            logger.info(
                "음악 채널 생성 완료: guild_id=%s channel_id=%s",
                guild.id,
                control_channel.id,
            )

        # ! 상태 업데이트, 기본 임베드 뷰 생성
        logger.debug("음악 패널 상태 갱신: guild_id=%s", guild.id)
        embed = self._make_default_embed()
        state.control_channel = control_channel
        state.control_view = await self._build_helper_view(guild.id)

        # 1) 저장된 ID 우선 시도
        fetched = False
        gid_key = str(guild.id)
        stored_id = self._panel_ids.get(gid_key)
        if stored_id:
            try:
                control_msg = await control_channel.fetch_message(stored_id)
                if (
                    control_msg
                    and control_msg.author == guild.me
                    and control_msg.embeds
                ):
                    em = control_msg.embeds[0]
                    if em.title in (PANEL_TITLE, embed.title):
                        logger.debug(
                            "저장된 음악 패널 메시지 재사용: guild_id=%s message_id=%s",
                            guild.id,
                            control_msg.id,
                        )
                        state.control_msg = control_msg
                        await self._edit_msg(state, embed, state.control_view)
                        fetched = True
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.info("저장된 패널 ID fetch 실패 -> fallback", exc_info=True)
                # 실패 시 dict에서 제거
                await self._del_panel_id(gid_key)

        if not fetched:
            # 2) 히스토리 스캔
            async for control_msg in control_channel.history(limit=50):
                if control_msg.author == guild.me and control_msg.embeds:
                    em = control_msg.embeds[0]
                    if em.title == PANEL_TITLE:
                        logger.debug(
                            "기존 음악 패널 임베드 발견: guild_id=%s message_id=%s",
                            guild.id,
                            control_msg.id,
                        )
                        state.control_msg = control_msg
                        # 발견 즉시 ID 저장
                        await self._set_panel_id(gid_key, control_msg.id)
                        await self._edit_msg(state, embed, state.control_view)
                        fetched = True
                        break

        if fetched:
            return

        # ! 없으면 새로 보내기
        state.control_msg = await control_channel.send(
            embed=embed, view=state.control_view
        )
        logger.info(
            "새 음악 패널 메시지 전송: guild_id=%s message_id=%s",
            guild.id,
            state.control_msg.id,
        )
        self._panel_ids[gid_key] = state.control_msg.id
        await self._set_panel_id(gid_key, state.control_msg.id)

    # === 부팅 직후 음악 채널 정리 ===
    async def _purge_music_channel_extras(self, guild: discord.Guild, limit: int = 500):
        """음악 채널에서 '패널 임베드' 메시지를 제외한 일반 사용자/과거 메세지를 정리.

        조건:
        - 채널명: DEFAULT_MUSIC_CHANNEL_NAME 또는 /채널설정 기능:음악 대상
        - 유지: 봇이 보낸 패널 메시지(제목이 PANEL_TITLE 또는 기본 패널 제목)
        - 나머지: 모두 삭제 (핀 고정은 존중 -> pinned True면 건너뜀)
        - 1회만 수행 (재연결 시 중복 제거 방지)
        """
        if guild.id in self._purged_guilds:
            return
        state = self._get_state(guild.id)
        channel = state.control_channel or await self._resolve_music_channel(guild)
        if channel is None:
            return
        panel_msg_id = (
            state.control_msg.id
            if state.control_msg
            else self._panel_ids.get(str(guild.id))
        )
        kept_ids = {panel_msg_id} if panel_msg_id else set()
        removed = 0
        try:
            async for msg in channel.history(limit=limit, oldest_first=False):
                if msg.pinned:
                    continue
                if kept_ids and msg.id in kept_ids:
                    continue
                # 패널 메시지 판별(혹시 id 저장 실패 케이스 대비)
                if (
                    msg.author == guild.me
                    and msg.embeds
                    and msg.embeds[0].title in (PANEL_TITLE, "🎵 신창섭의 다해줬잖아")
                ):
                    # 패널로 간주하고 ID 업데이트 후 유지
                    if not kept_ids:
                        kept_ids.add(msg.id)
                    continue
                try:
                    await msg.delete()
                    removed += 1
                except discord.HTTPException:
                    continue
        finally:
            if removed:
                dbg(f"_purge_music_channel_extras: guild={guild.id} removed={removed}")
            self._purged_guilds.add(guild.id)

    # ?완
    # !노래 재생 or 대기열
    async def _play_url_now(
        self,
        interaction: discord.Interaction,
        url: str,
        *,
        success_prefix: str = "▶ 재생",
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)

        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
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
            return
        voice_client = voice_result.voice_client
        if voice_client is None:
            return
        if transition_log := describe_voice_transition(
            voice_result,
            action="_play_url_now",
            user_channel=user_channel,
        ):
            dbg(transition_log)

        try:
            player = await prepare_music_player(
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
            return

        replacing = is_voice_client_active(voice_client)
        state.is_stopping = False
        state.is_skipping = False
        if replacing:
            state.is_seeking = True
            voice_client.stop()

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
            if replacing:
                state.is_seeking = False

        await self._send_auto_delete(
            interaction,
            playback_start.confirmation_message,
        )

    async def _play(self, interaction, url: str, skip_defer: bool = False):
        dbg(
            f"_play: called url={url} guild={interaction.guild.id} user={interaction.user.id}"
        )
        # ? 검색어 처리
        if not is_http_url(url):
            # ytsearch로 상위 10개까지 뽑되
            info = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: search_ytdl.extract_info(f"ytsearch10:{url}", download=False),
            )
            dbg(
                f"_play: search info keys={list(info.keys()) if isinstance(info,dict) else type(info)}"
            )
            search_result = build_music_search_action(url, info)
            if search_result.user_message:
                await self._send_ephemeral_response(
                    interaction, search_result.user_message
                )
                return

            dbg(f"_play: videos_count={len(search_result.videos)}")

            # Embed  View 생성
            dbg(
                f"_play: description built length={len(search_result.embed_description or '')}"
            )
            embed = Embed(
                title=search_result.embed_title,
                description=search_result.embed_description,
                color=0xFFC0CB,
            )
            view = SearchResultView(self, search_result.videos)
            # ! 완료 메시지
            await self._send_ephemeral_response(interaction, embed=embed, view=view)
            # 검색 모드에서는 여기서 종료 (선택은 SelectView가 처리)
            return

        # ? URL 재생
        if not skip_defer:
            await interaction.response.defer(thinking=True, ephemeral=True)

        # ! 기본정보 로드
        guild_id = interaction.guild.id
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
            return
        voice_client = voice_result.voice_client
        if voice_client is None:
            return
        if transition_log := describe_voice_transition(
            voice_result,
            action="_play",
            user_channel=user_channel,
        ):
            dbg(transition_log)

        # ! 이미 재생(또는 일시정지) 중이면 URL만 큐에 추가
        state = self._get_state(interaction.guild.id)
        self._cancel_idle_disconnect(state)
        url_play_result = begin_url_play_action(
            state,
            url=url,
            requester=interaction.user,
            is_active=is_voice_client_active(voice_client),
        )
        if not url_play_result.should_prepare:
            dbg(f"_play: appended URL to queue size={url_play_result.queue_size}")
            # 메타데이터는 백그라운드에서 채움(가벼운 작업으로 유지)
            self._spawn_bg(self._fill_queue_meta(url_play_result.queued_track))
            # ! 완료 메시지
            await self._send_auto_delete(interaction, url_play_result.user_message)
            return

        # ! 재생 중이 아니면 지금 URL로 바로 준비 후 재생
        try:
            player = await prepare_music_player(
                YTDLSource.from_url,
                url,
                loop=self.bot.loop,
                requester=interaction.user,
                include_ffmpeg_guidance=True,
            )
            dbg(f"_play: prepared player title={getattr(player,'title',None)}")
        except MusicPlayerPreparationError as exc:
            dbg(f"_play: {exc.failure.debug_message}")
            await self._send_auto_delete(
                interaction,
                exc.failure.user_message,
                delay=exc.failure.delete_after,
            )
            return

        # !상태 업데이트 및 재생 시작
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

    async def _pause(self, interaction):
        # !기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
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
        result = begin_stop_playback_action(state)
        await voice_client.disconnect()

        # ! reset panel
        state.control_view = await self._build_helper_view(interaction.guild.id)
        embed = self._make_default_embed()
        await self._edit_msg(state, embed, state.control_view)

        # ! 재생 상태 완전 초기화
        reset_music_playback_state(state)

        # ! 메시지
        await self._send_auto_delete(interaction, result.user_message)

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

    async def _restart_updater(self, guild_id: int):
        dbg("_restart_updater: called")
        # ! 기본정보 로드
        state = self._get_state(guild_id)

        # ! task 종료
        if state.updater_task:
            dbg("_restart_updater: cancel existing updater_task")
            state.updater_task.cancel()

        # ! task 종료 대기
        while state.updater_task:
            dbg("_restart_updater: waiting for updater_task to finish")
            await asyncio.sleep(0.5)

        # ! task 재등록
        dbg("_restart_updater: creating new updater task")
        state.updater_task = self._spawn_bg(self._updater_loop(guild_id))
        await asyncio.sleep(1)

    async def _seek(self, interaction: discord.Interaction, seconds: int):
        dbg(f"_seek: seconds={seconds}")
        # ! 기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
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
            player = await prepare_music_player(
                YTDLSource.from_url,
                state.player.webpage_url,
                loop=self.bot.loop,
                start_time=seconds,
                requester=state.player.requester,
            )
            # ! 멈추고 재생 위치부터 새 소스 생성
            begin_seek_playback_action(state)
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
            await self._restart_updater(guild_id)
            # ! 메시지 수정(임베드, 뷰)
            embed = self._make_playing_embed(
                state.player,
                guild_id,
                elapsed=result.elapsed,
            )
            await self._edit_msg(state, embed, state.control_view)
            # ! 메시지
            await self._send_auto_delete(interaction, result.user_message)
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
            # 실패 시 is_seeking 안전 복구
            result = fail_seek_playback_action(state)
            await self._send_auto_delete(
                interaction,
                result.user_message,
                delay=result.delete_after,
            )

    # ?완료
    async def _toggle_loop(self, interaction: discord.Interaction):
        """🔁 반복 모드 토글"""
        await interaction.response.defer(thinking=True, ephemeral=True)
        # ! 상태 업데이트
        state = self._get_state(interaction.guild.id)
        voice_client = interaction.guild.voice_client
        if voice_client and (error := same_voice_channel_error(interaction, voice_client)):
            await self._send_auto_delete(interaction, error)
            return
        result = toggle_loop_action(state)
        # ! 메시지
        await self._send_auto_delete(interaction, result.user_message)

    # ?완료
    def _vc_play(
        self, guild_id: int = None, interaction: discord.Interaction = None, source=None
    ):
        # ! 재생 및 다음 곡 콜백 등록
        def _after_play(error):
            if error:
                dbg(f"_after_play: error={error}")
            else:
                dbg("_after_play: finished")

            def _schedule_song_end() -> None:
                self._spawn_bg(self._on_song_end(guild_id))

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

    async def _on_song_end(self, guild_id: int):
        dbg("_on_song_end: called")
        # ! 기본정보 로드
        state = self._get_state(guild_id)

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
            self._spawn_bg(self._on_song_end(guild_id))
            return
        self._cancel_idle_disconnect(state)
        start_music_playback_state(state, player, started_at=time.time())
        embed = self._make_playing_embed(state.player, guild_id)
        await self._edit_msg(state, embed, state.control_view)
        self._vc_play(guild_id, source=state.player.source)
        await self._restart_updater(guild_id)

    @app_commands.command(
        name="음악", description="음악 재생 상태와 컨트롤 버튼을 보여줍니다."
    )
    async def 음악(self, interaction: discord.Interaction):
        logger.debug("음악 패널 명령 시작: guild_id=%s", interaction.guild.id)
        # !메시지
        await self._send_ephemeral_response(
            interaction,
            "음악 컨트롤 패널을 설정 중입니다…",
        )
        # !길드별 State 초기화
        await self._get_or_create_panel(interaction.guild)
        logger.info("음악 패널 갱신 완료: guild_id=%s", interaction.guild.id)

    @app_commands.command(name="재생", description="유튜브 URL을 재생합니다.")
    @app_commands.rename(url="검색어")
    @app_commands.describe(url="재생할 유튜브 URL 혹은 검색어")
    async def 재생(self, interaction: discord.Interaction, url: str):
        await self._play(interaction, url)

    @app_commands.command(name="일시정지", description="음악 일시정지")
    async def 일시정지(self, interaction: discord.Interaction):
        await self._pause(interaction)

    @app_commands.command(name="다시재생", description="일시정지된 음악 재생")
    async def 다시재생(self, interaction: discord.Interaction):
        await self._resume(interaction)

    @app_commands.command(name="정지", description="음악 정지 및 퇴장")
    async def 정지(self, interaction: discord.Interaction):
        await self._stop(interaction)

    @app_commands.command(name="스킵", description="현재 재생 중인 곡을 넘깁니다.")
    async def 스킵(self, interaction: discord.Interaction):
        await self._skip(interaction)

    @app_commands.command(name="대기열", description="현재 음악 대기열을 보여줍니다.")
    async def 대기열(self, interaction: discord.Interaction):
        await self._show_queue(interaction)

    @app_commands.command(name="구간이동", description="현재 곡의 재생 위치를 이동합니다.")
    @app_commands.describe(시간="이동할 시간. 예: 1:23 또는 83")
    async def 구간이동(self, interaction: discord.Interaction, 시간: str):
        try:
            seconds = parse_seek_seconds(시간)
        except ValueError:
            await self._send_ephemeral_response(
                interaction,
                "❌ 시간 형식이 올바르지 않습니다. 예: 1:23 또는 83",
            )
            return
        await self._seek(interaction, seconds)

    @app_commands.command(name="반복", description="현재 곡 반복 모드를 켜거나 끕니다.")
    async def 반복(self, interaction: discord.Interaction):
        await self._toggle_loop(interaction)

    @app_commands.command(name="대기열삭제", description="대기열에서 지정한 번호의 곡을 삭제합니다.")
    @app_commands.describe(번호="삭제할 대기열 번호")
    async def 대기열삭제(self, interaction: discord.Interaction, 번호: int):
        await self._remove_from_queue(interaction, 번호)

    @app_commands.command(name="대기열비우기", description="현재 대기열을 모두 비웁니다.")
    async def 대기열비우기(self, interaction: discord.Interaction):
        await self._clear_queue(interaction)

    @app_commands.command(name="대기열이동", description="대기열 곡의 위치를 변경합니다.")
    @app_commands.describe(현재번호="현재 대기열 번호", 새번호="옮길 대기열 번호")
    async def 대기열이동(
        self,
        interaction: discord.Interaction,
        현재번호: int,
        새번호: int,
    ):
        await self._move_queue(interaction, 현재번호, 새번호)

    @app_commands.command(name="셔플", description="현재 대기열 순서를 무작위로 섞습니다.")
    async def 셔플(self, interaction: discord.Interaction):
        await self._shuffle_queue(interaction)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Music Cog on_ready 처리 시작")
        # ! 모든 길드의 패널 설정
        for guild in self.bot.guilds:
            try:
                logger.debug(
                    "on_ready 길드 음악 상태 로드: guild_id=%s guild=%s",
                    guild.id,
                    guild,
                )
                await self._get_or_create_panel(guild)
                # 패널 확보 후 불필요 메세지 정리
                await self._purge_music_channel_extras(guild)
            except Exception:
                logger.exception("[on_ready] 길드 %s 패널 생성 실패", guild.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """음악 전용 채널에서 일반 유저 메시지를 자동 삭제.

        - 채널명: DEFAULT_MUSIC_CHANNEL_NAME 또는 /채널설정 기능:음악 대상
        - 봇 메시지는 허용
        - 패널/컨트롤 유지
        - Slash 명령은 별도의 application interaction이라 일반 메시지 객체가 아니므로 별도 처리 불필요
        """
        # DM / 시스템 / 웹훅 제외
        if not message.guild or message.type != discord.MessageType.default:
            return
        if message.author.bot:
            return
        if not await self._is_music_control_channel(message):
            return
        # 유저가 붙여넣은 일반 텍스트/URL 등 모두 삭제
        try:
            await message.delete()
        except discord.HTTPException:
            return
        # 경고 메시지 (쿨다운 내 중복 표시 방지)
        now = time.time()
        last = self._last_warn.get(message.author.id, 0)
        if now - last < self._warn_cooldown:
            return
        self._last_warn[message.author.id] = now
        await self._send_channel_auto_delete(
            message.channel,
            f"{message.author.mention} 이 채널은 음악 명령 전용입니다. 다른 대화는 다른 채널을 이용해주세요!",
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, discord.errors.ClientException):
            return
        logger.exception("music command error", exc_info=(type(error), error, error.__traceback__))


async def setup(bot: commands.Bot):
    cog = MusicCog(bot)
    await bot.add_cog(cog)
    bot.add_view(MusicHelperView(cog))
    logger.info("Music Cog setup 완료")
