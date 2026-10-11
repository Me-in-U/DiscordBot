from __future__ import annotations

import time
from typing import Optional, Tuple, Any
import aiomysql
import discord
from discord import Embed, TextChannel
from util.guild.channel_settings import get_channel
from util.music.embeds import (
    PANEL_TITLE,
    make_default_music_embed,
    make_playing_music_embed,
)
from util.music.state import GuildMusicState
from util.music.progress import (
    make_progress_bar as build_music_progress_bar,
    make_timeline_line as build_music_timeline_line,
)
from util.music.panel_store import (
    delete_music_panel_id,
    load_music_panel_ids,
    save_music_panel_id,
)
from util.music.source import YTDLSource
from .runtime import DEFAULT_MUSIC_CHANNEL_NAME, MUSIC_CHANNEL_TYPE, dbg, logger


class MusicPanelMixin:
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

    def _make_default_embed(self) -> Embed:
        try:
            return make_default_music_embed(
                bot_avatar_url=self.bot.user.avatar.url,
            )
        except (AttributeError, TypeError, ValueError):
            logger.exception("기본 음악 패널 임베드 생성 실패")
            raise

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

    async def _get_or_create_panel(self, guild: discord.Guild):
        # ! 상태 기본값 설정
        async with self._music_operation(guild.id):
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
            state.control_channel = control_channel
            if state.player is not None:
                state.control_view = await self._build_control_view(guild.id, state)
                now = state.paused_at if state.paused_at is not None else time.time()
                embed = self._make_playing_embed(state.player, guild.id, max(0, int(now - state.start_ts)))
            else:
                state.control_view = await self._build_helper_view(guild.id)
                embed = self._make_default_embed()

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
