from __future__ import annotations

import time
import aiomysql
import discord
from util.music.favorites import (
    MusicFavorite,
    MusicFavoriteSavePayload,
    apply_music_favorite_cache_store_action,
    build_music_favorite_cache_hit_result_action,
    build_music_favorite_cache_load_action,
    build_music_favorite_cache_store_action,
    build_music_favorite_current_track_save_action,
    build_music_favorite_load_failure_action,
    build_music_favorite_manager_open_action,
    build_music_favorite_panel_refresh_action,
    build_music_favorite_play_action,
    build_music_favorite_play_request_action,
    build_music_favorite_save_response_action,
    build_music_favorite_search_entry_save_action,
    build_music_favorite_search_request_action,
    current_player_to_music_favorite,
    get_music_favorite,
    list_music_favorites,
    save_music_favorite_payload,
)
from util.music.state import GuildMusicState
from util.music.search import build_music_search_flow
from util.music.source import YTDL_EXECUTOR, search_ytdl
from util.music.views import MusicControlView, MusicFavoriteManageView, MusicHelperView
from .runtime import logger


class MusicFavoritesMixin:
    async def _load_music_favorites(
        self,
        guild_id: int,
        *,
        refresh: bool = False,
    ) -> list[MusicFavorite]:
        cache_action = build_music_favorite_cache_load_action(
            guild_id=guild_id,
            cache=self._favorite_cache,
            refresh=refresh,
        )
        if cache_action.should_use_cache:
            hit_action = build_music_favorite_cache_hit_result_action(cache_action)
            return hit_action.favorites
        try:
            favorites = await list_music_favorites(cache_action.guild_id)
        except (aiomysql.Error, OSError, TimeoutError, TypeError, ValueError, KeyError):
            failure_action = build_music_favorite_load_failure_action(
                guild_id=cache_action.guild_id,
            )
            logger.warning(
                "음악 즐겨찾기 로드 실패: guild_id=%s",
                failure_action.guild_id,
                exc_info=True,
            )
            return self._favorite_cache.get(cache_action.guild_id, failure_action.favorites)
        store_action = build_music_favorite_cache_store_action(
            guild_id=cache_action.guild_id,
            favorites=favorites,
        )
        return apply_music_favorite_cache_store_action(
            self._favorite_cache,
            store_action,
        )

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

        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)
        search_result = await build_music_search_flow(
            favorite_search_action.query,
            search_ytdl,
            executor=YTDL_EXECUTOR,
            favorite_slot=favorite_search_action.slot,
        )
        await self._send_music_search_response(
            interaction,
            search_result,
            favorite_slot=favorite_search_action.slot,
        )

    async def _save_music_favorite(
        self,
        interaction: discord.Interaction,
        payload: MusicFavoriteSavePayload,
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            save_result = await save_music_favorite_payload(payload)
        except (aiomysql.Error, OSError, TimeoutError, TypeError, ValueError):
            logger.warning("음악 즐겨찾기 저장 실패: guild_id=%s slot=%s", payload.guild_id, payload.slot, exc_info=True)
            await self._send_auto_delete(interaction, "❌ 즐겨찾기를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.")
            return
        response_action = build_music_favorite_save_response_action(save_result)
        if response_action.should_refresh_favorites:
            await self._load_music_favorites(response_action.guild_id, refresh=True)
        if response_action.should_refresh_panel:
            try:
                await self._refresh_music_panel_for_favorites(response_action.guild_id)
            except (discord.HTTPException, aiomysql.Error, OSError, TimeoutError):
                logger.warning("즐겨찾기 저장 후 음악 패널 갱신 실패", exc_info=True)
        await self._send_auto_delete(
            interaction,
            response_action.user_message,
        )

    async def _save_search_entry_as_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
        entry: dict,
    ) -> None:
        save_action = build_music_favorite_search_entry_save_action(
            guild_id=interaction.guild.id,
            slot=slot,
            entry=entry,
            updated_by=interaction.user.id,
        )
        await self._save_music_favorite(
            interaction,
            save_action.payload,
        )

    async def _save_current_track_as_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        favorite = current_player_to_music_favorite(guild_id, state.player)
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
        async with self._music_operation(guild_id):
            state = self._get_state(guild_id)
            panel_action = build_music_favorite_panel_refresh_action(
                guild_id=guild_id,
                has_control_message=state.control_msg is not None,
                has_control_channel=state.control_channel is not None,
                has_player=state.player is not None,
            )
            if not panel_action.should_refresh:
                return
            if panel_action.should_use_playing_panel:
                state.control_view = await self._build_control_view(
                    panel_action.guild_id,
                    state,
                )
                now = state.paused_at if state.paused_at is not None else time.time()
                elapsed = max(0, int(now - state.start_ts)) if state.start_ts else 0
                embed = self._make_playing_embed(state.player, panel_action.guild_id, elapsed)
            else:
                state.control_view = await self._build_helper_view(panel_action.guild_id)
                embed = self._make_default_embed()
            await self._edit_msg(state, embed, state.control_view)

    async def _play_music_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)
        play_request = build_music_favorite_play_request_action(slot)
        try:
            favorite = await get_music_favorite(interaction.guild.id, play_request.slot)
        except (aiomysql.Error, OSError, TimeoutError, TypeError, ValueError, KeyError):
            logger.warning("음악 즐겨찾기 조회 실패", exc_info=True)
            await self._send_ephemeral_response(interaction, "❌ 즐겨찾기를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
            return
        play_result = build_music_favorite_play_action(
            slot=play_request.slot,
            favorite=favorite,
        )
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
