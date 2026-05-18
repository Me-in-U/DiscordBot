import unittest

from cogs.music import GuildMusicState, MusicControlView, MusicHelperView
from util.music_favorites import (
    MusicFavorite,
    build_music_favorite_button_label,
    validate_music_favorite_slot,
)


class MusicFavoriteTests(unittest.IsolatedAsyncioTestCase):
    def test_favorite_button_label_truncates_long_title(self):
        favorite = MusicFavorite(
            guild_id=1,
            slot=1,
            title="가나다라마바사아자차카타파하",
            url="https://example.com/watch?v=1",
        )

        self.assertEqual(
            build_music_favorite_button_label(1, favorite),
            "1 가나다라마바사아자차카타…",
        )

    def test_favorite_slot_is_limited_to_one_through_five(self):
        self.assertEqual(validate_music_favorite_slot(5), 5)
        with self.assertRaises(ValueError):
            validate_music_favorite_slot(6)

    async def test_default_music_view_shows_search_manage_and_five_favorite_slots(self):
        favorite = MusicFavorite(
            guild_id=1,
            slot=2,
            title="저장된 노래",
            url="https://example.com/watch?v=2",
        )

        view = MusicHelperView(_Cog(), [favorite])
        labels = [item.label for item in view.children]

        self.assertEqual(labels[:2], ["🔍 검색", "⭐ 즐겨찾기"])
        self.assertEqual(labels[2:], ["1 빈칸", "2 저장된 노래", "3 빈칸", "4 빈칸", "5 빈칸"])

    async def test_playing_music_view_shows_favorite_slots_after_control_buttons(self):
        favorite = MusicFavorite(
            guild_id=1,
            slot=1,
            title="저장된 노래",
            url="https://example.com/watch?v=1",
        )

        view = MusicControlView(_Cog(), GuildMusicState(), [favorite])
        labels = [item.label for item in view.children]

        self.assertIn("🔍 검색", labels)
        self.assertIn("⭐ 즐겨찾기", labels)
        self.assertEqual(labels[-5:], ["1 저장된 노래", "2 빈칸", "3 빈칸", "4 빈칸", "5 빈칸"])


class _Cog:
    async def _open_music_favorite_manager(self, interaction):
        return None

    async def _play_music_favorite(self, interaction, slot):
        return None

    async def _pause(self, interaction):
        return None

    async def _skip(self, interaction):
        return None

    async def _stop(self, interaction):
        return None

    async def _show_queue(self, interaction):
        return None

    async def _toggle_loop(self, interaction):
        return None


if __name__ == "__main__":
    unittest.main()
