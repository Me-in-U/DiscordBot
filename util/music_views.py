from __future__ import annotations

from typing import Any

import discord
from discord.ui import Button, View

from util.music_favorites import (
    MUSIC_FAVORITE_SLOT_MAX,
    MusicFavorite,
    build_music_favorite_button_label,
    build_music_favorite_current_save_button_action,
    build_music_favorite_manager_selection_action,
    build_music_favorite_search_modal_action,
    build_music_favorite_search_submit_action,
)
from util.music_queue import parse_seek_seconds


def _favorite_by_slot(favorites: list[MusicFavorite]) -> dict[int, MusicFavorite]:
    return {favorite.slot: favorite for favorite in favorites}


class SearchResultView(View):
    def __init__(
        self,
        cog: Any,
        videos: list[dict],
        *,
        favorite_slot: int | None = None,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.favorite_slot = favorite_slot

        vids = list(videos[:10])
        if not vids:
            self.add_item(
                Button(
                    label="❌ 검색 결과가 없습니다",
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                )
            )
            return

        for i, video in enumerate(vids, start=1):
            url = video.get("url")
            if not isinstance(url, str):
                continue
            btn = Button(
                label=str(i),
                style=discord.ButtonStyle.secondary,
                custom_id=f"search_pick_{i}",
                row=(i - 1) // 5,
            )

            async def _on_pick(interaction: discord.Interaction, _entry=video):
                await interaction.response.edit_message(
                    content="선택 처리 중...",
                    embed=None,
                    view=None,
                    delete_after=0.1,
                )
                if self.favorite_slot is not None:
                    await self.cog._save_search_entry_as_favorite(
                        interaction,
                        self.favorite_slot,
                        _entry,
                    )
                    return
                await self.cog._play_from_search_pick(interaction, _entry)

            btn.callback = _on_pick
            self.add_item(btn)


def _add_music_favorite_buttons(
    view: View,
    cog: Any,
    favorites: list[MusicFavorite],
    *,
    row: int,
) -> None:
    favorite_map = _favorite_by_slot(favorites)
    for slot in range(1, MUSIC_FAVORITE_SLOT_MAX + 1):
        favorite = favorite_map.get(slot)
        btn = Button(
            label=build_music_favorite_button_label(slot, favorite),
            style=discord.ButtonStyle.secondary,
            custom_id=f"music_favorite_play_{slot}",
            row=row,
            disabled=favorite is None,
        )

        async def _on_favorite(
            interaction: discord.Interaction,
            _slot: int = slot,
        ):
            await cog._play_music_favorite(interaction, _slot)

        btn.callback = _on_favorite
        view.add_item(btn)


class FavoriteSearchModal(discord.ui.Modal, title="즐겨찾기 음악 검색"):
    query = discord.ui.TextInput(
        label="저장할 음악 제목이나 링크",
        placeholder='예: "신창섭 다해줬잖아" or https://www.youtube.com/watch?v=...',
    )

    def __init__(self, cog: Any, slot: int):
        super().__init__()
        self.cog = cog
        modal_action = build_music_favorite_search_modal_action(slot)
        self.slot = modal_action.slot

    async def on_submit(self, interaction: discord.Interaction):
        submit_action = build_music_favorite_search_submit_action(
            slot=self.slot,
            query_value=self.query.value,
        )
        await self.cog._search_music_for_favorite_slot(
            interaction,
            submit_action.slot,
            submit_action.query,
        )


class MusicFavoriteSlotSelect(discord.ui.Select):
    def __init__(self, parent: "MusicFavoriteManageView"):
        self.manager_view = parent
        favorite_map = _favorite_by_slot(parent.favorites)
        options = []
        for slot in range(1, MUSIC_FAVORITE_SLOT_MAX + 1):
            favorite = favorite_map.get(slot)
            label = build_music_favorite_button_label(slot, favorite)
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(slot),
                    default=slot == parent.selected_slot,
                )
            )
        super().__init__(
            placeholder="수정할 즐겨찾기 번호 선택",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        selection = build_music_favorite_manager_selection_action(self.values[0])
        self.manager_view.selected_slot = selection.selected_slot
        for option in self.options:
            option.default = selection.is_default_value(option.value)
        await interaction.response.edit_message(
            content=selection.status_text,
            view=self.manager_view,
        )


class MusicFavoriteManageView(View):
    def __init__(
        self,
        cog: Any,
        *,
        guild_id: int,
        favorites: list[MusicFavorite],
        current_track: MusicFavorite | None = None,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = int(guild_id)
        self.favorites = list(favorites)
        self.current_track = current_track
        self.selected_slot = 1
        self.add_item(MusicFavoriteSlotSelect(self))

        search_btn = Button(
            label="🔎 검색해서 저장",
            style=discord.ButtonStyle.primary,
            custom_id="music_favorite_search",
            row=1,
        )
        current_action = build_music_favorite_current_save_button_action(
            selected_slot=self.selected_slot,
            current_track=current_track,
        )
        current_btn = Button(
            label="⭐ 현재곡 저장",
            style=discord.ButtonStyle.success,
            custom_id="music_favorite_current",
            row=1,
            disabled=current_action.disabled,
        )
        search_btn.callback = self._on_search
        current_btn.callback = self._on_current
        self.add_item(search_btn)
        self.add_item(current_btn)

    def status_text(self) -> str:
        return build_music_favorite_manager_selection_action(
            self.selected_slot
        ).status_text

    async def _on_search(self, interaction: discord.Interaction):
        modal_action = build_music_favorite_search_modal_action(self.selected_slot)
        await interaction.response.send_modal(
            FavoriteSearchModal(self.cog, modal_action.slot)
        )

    async def _on_current(self, interaction: discord.Interaction):
        current_action = build_music_favorite_current_save_button_action(
            selected_slot=self.selected_slot,
            current_track=self.current_track,
        )
        await self.cog._save_current_track_as_favorite(
            interaction,
            current_action.slot,
        )


class MusicHelperView(View):
    def __init__(
        self,
        cog: Any,
        favorites: list[MusicFavorite] | None = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        favorites = favorites or []

        search_btn = Button(
            label="🔍 검색",
            style=discord.ButtonStyle.primary,
            custom_id="music_search",
            row=0,
        )
        favorite_btn = Button(
            label="⭐ 즐겨찾기",
            style=discord.ButtonStyle.secondary,
            custom_id="music_favorite_manage",
            row=0,
        )
        search_btn.callback = self._on_search
        favorite_btn.callback = self._on_favorite_manage
        self.add_item(search_btn)
        self.add_item(favorite_btn)
        _add_music_favorite_buttons(self, cog, favorites, row=1)

    async def _on_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SearchModal(self.cog))

    async def _on_favorite_manage(self, interaction: discord.Interaction):
        await self.cog._open_music_favorite_manager(interaction)


class MusicControlView(View):
    def __init__(
        self,
        cog: Any,
        state: Any,
        favorites: list[MusicFavorite] | None = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state
        self.favorites = favorites or []

        if state.paused_at:
            self.resume_btn = Button(
                label="▶️ 다시재생",
                style=discord.ButtonStyle.primary,
                custom_id="music_resume",
                row=0,
            )
            self.resume_btn.callback = self._on_resume
            self.add_item(self.resume_btn)
        else:
            self.pause_btn = Button(
                label="⏸️ 일시정지",
                style=discord.ButtonStyle.primary,
                custom_id="music_pause",
                row=0,
            )
            self.pause_btn.callback = self._on_pause
            self.add_item(self.pause_btn)

        self.add_control_buttons()
        _add_music_favorite_buttons(self, cog, self.favorites, row=3)

    def add_control_buttons(self):
        skip_btn = Button(
            label="⏭️ 스킵",
            style=discord.ButtonStyle.success,
            custom_id="music_skip",
            row=0,
        )
        stop_btn = Button(
            label="⏹️ 정지",
            style=discord.ButtonStyle.danger,
            custom_id="music_stop",
            row=0,
        )
        queue_btn = Button(
            label="🔀 대기열",
            style=discord.ButtonStyle.secondary,
            custom_id="music_queue",
            row=1,
        )
        seek_btn = Button(
            label="⏩ 구간이동",
            style=discord.ButtonStyle.secondary,
            custom_id="music_seek",
            row=1,
        )
        loop_btn = Button(
            label="🔁 반복",
            style=discord.ButtonStyle.secondary,
            custom_id="music_loop",
            row=1,
        )
        search_btn = Button(
            label="🔍 검색",
            style=discord.ButtonStyle.primary,
            custom_id="music_search_2",
            row=2,
        )
        favorite_btn = Button(
            label="⭐ 즐겨찾기",
            style=discord.ButtonStyle.secondary,
            custom_id="music_favorite_manage",
            row=2,
        )

        skip_btn.callback = self._on_skip
        stop_btn.callback = self._on_stop
        queue_btn.callback = self._on_queue
        seek_btn.callback = self._on_seek
        loop_btn.callback = self._on_loop
        search_btn.callback = self._on_search
        favorite_btn.callback = self._on_favorite_manage

        for button in [
            skip_btn,
            stop_btn,
            queue_btn,
            seek_btn,
            loop_btn,
            search_btn,
            favorite_btn,
        ]:
            self.add_item(button)

    async def _on_pause(self, interaction: discord.Interaction):
        await self.cog._pause(interaction)

    async def _on_resume(self, interaction: discord.Interaction):
        await self.cog._resume(interaction)

    async def _on_skip(self, interaction: discord.Interaction):
        await self.cog._skip(interaction)

    async def _on_stop(self, interaction: discord.Interaction):
        await self.cog._stop(interaction)

    async def _on_queue(self, interaction: discord.Interaction):
        await self.cog._show_queue(interaction)

    async def _on_seek(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SeekModal(self.cog))

    async def _on_loop(self, interaction: discord.Interaction):
        await self.cog._toggle_loop(interaction)

    async def _on_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SearchModal(self.cog))

    async def _on_favorite_manage(self, interaction: discord.Interaction):
        await self.cog._open_music_favorite_manager(interaction)


class SeekModal(discord.ui.Modal, title="구간이동"):
    time = discord.ui.TextInput(
        label="가록될 시간 (mm:ss 또는 초)", placeholder="예: 1:23 또는 83"
    )

    def __init__(self, cog: Any):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        text = (self.time.value or "").strip()
        try:
            seconds = parse_seek_seconds(text)
        except ValueError:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ 시간 형식이 올바르지 않습니다. 예: 1:23 또는 83",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "❌ 시간 형식이 올바르지 않습니다. 예: 1:23 또는 83",
                    ephemeral=True,
                )
            return
        await self.cog._seek(interaction, seconds)


class SearchModal(discord.ui.Modal, title="음악검색"):
    query = discord.ui.TextInput(
        label="음악의 제목이나 링크를 입력하세요",
        placeholder='예: "신창섭 다해줬잖아" or https://www.youtube.com/watch?v=DYbt8rmJT40',
    )

    def __init__(self, cog: Any):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._play(interaction, self.query.value)
