import unittest
import warnings
from types import SimpleNamespace

from util.music.favorites import MusicFavorite

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="'audioop' is deprecated and slated for removal in Python 3.13",
        category=DeprecationWarning,
    )
    from util.music_views import MusicControlView, MusicHelperView, SearchResultView


class MusicViewHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_result_view_has_finite_timeout_and_number_buttons(self):
        view = SearchResultView(
            _Cog(),
            [{"url": "https://www.youtube.com/watch?v=1", "title": "one"}],
        )

        self.assertEqual(view.timeout, 120)
        self.assertEqual([item.label for item in view.children], ["1"])
        self.assertEqual([item.custom_id for item in view.children], ["search_pick_1"])

    async def test_helper_view_exposes_search_manage_and_favorite_slots(self):
        favorite = MusicFavorite(
            guild_id=1,
            slot=3,
            title="저장된 노래",
            url="https://example.com/watch?v=3",
        )

        view = MusicHelperView(_Cog(), [favorite])

        self.assertEqual(
            [item.label for item in view.children],
            ["🔍 검색", "⭐ 즐겨찾기", "1 빈칸", "2 빈칸", "3 저장된 노래", "4 빈칸", "5 빈칸"],
        )

    async def test_control_view_exposes_playback_queue_search_and_favorites(self):
        state = SimpleNamespace(paused_at=None)
        view = MusicControlView(_Cog(), state, [])
        labels = [item.label for item in view.children]

        self.assertIn("⏸️ 일시정지", labels)
        self.assertIn("🔀 대기열", labels)
        self.assertIn("🔍 검색", labels)
        self.assertEqual(labels[-5:], ["1 빈칸", "2 빈칸", "3 빈칸", "4 빈칸", "5 빈칸"])


class _Cog:
    async def _save_search_entry_as_favorite(self, interaction, slot, entry):
        return None

    async def _play_from_search_pick(self, interaction, entry):
        return None

    async def _play_music_favorite(self, interaction, slot):
        return None

    async def _open_music_favorite_manager(self, interaction):
        return None

    async def _pause(self, interaction):
        return None

    async def _resume(self, interaction):
        return None

    async def _skip(self, interaction):
        return None

    async def _stop(self, interaction):
        return None

    async def _show_queue(self, interaction):
        return None

    async def _toggle_loop(self, interaction):
        return None
