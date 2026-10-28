from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Coroutine, Any
import discord
from discord import Embed, app_commands
from discord.ext import commands
from util.music.favorites import MusicFavorite
from util.music.queue import (
    QueuedTrack,
    _track_title,
    build_queue_preview,
    move_queue_track,
    parse_seek_seconds,
    remove_queue_track,
    shuffle_queue,
)
from util.music.state import GuildMusicState
from util.voice_session import voice_lock
from util.music.views import MusicControlView, MusicHelperView
from dotenv import load_dotenv
from .runtime import logger

from .favorites import MusicFavoritesMixin
from .panel import MusicPanelMixin
from .playback import MusicPlaybackMixin
from .controls import MusicControlsMixin
from .queue import MusicQueueMixin
from .requests import MusicRequestsMixin

load_dotenv()


class MusicCog(
    MusicFavoritesMixin,
    MusicPanelMixin,
    MusicPlaybackMixin,
    MusicControlsMixin,
    MusicQueueMixin,
    MusicRequestsMixin,
    commands.Cog,
):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}  # 길드별 상태 저장
        # 백그라운드 태스크 레퍼런스 보관(조기 GC 방지)
        self._bg_tasks: set[asyncio.Task] = set()
        # 패널 메시지 ID 저장 로드
        self._panel_ids: dict[str, int] = {}
        self._favorite_cache: dict[int, list[MusicFavorite]] = {}

    async def cog_load(self):
        self._panel_ids = await self._load_panel_ids()

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

    def _get_state(self, guild_id: int) -> GuildMusicState:
        return self.states.setdefault(guild_id, GuildMusicState(operation_lock=voice_lock(guild_id)))

    @asynccontextmanager
    async def _music_operation(self, guild_id: int):
        state = self._get_state(guild_id)
        task = asyncio.current_task()
        # 검색 선택에서 URL 재생으로 이어지는 같은 작업은 잠금을 다시 잡지 않는다.
        if state.operation_owner is task:
            yield
            return
        async with state.operation_lock:
            state.operation_owner = task
            try:
                yield
            finally:
                state.operation_owner = None

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
            view_kwargs = {"view": view} if view is not None else {}
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
                    **view_kwargs,
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    content,
                    embed=embed,
                    **view_kwargs,
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

    async def _auto_delete(self, msg: discord.Message, delay: float = 5.0):
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except discord.HTTPException:
            pass

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
            except Exception:
                logger.exception("[on_ready] 길드 %s 패널 생성 실패", guild.id)

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
