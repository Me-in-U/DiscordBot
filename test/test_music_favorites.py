import unittest

from cogs.music import GuildMusicState, MusicCog, MusicControlView, MusicHelperView
from util.music_favorites import (
    MusicFavorite,
    build_music_favorite_button_label,
    current_player_to_music_favorite,
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

    def test_current_player_is_converted_to_favorite_snapshot(self):
        player = _Player(
            title="재생 중인 노래",
            webpage_url="https://youtube.com/watch?v=abc",
            data={
                "duration": 123,
                "uploader": "업로더",
                "thumbnail": "https://example.com/thumb.jpg",
            },
        )

        favorite = current_player_to_music_favorite(10, player)

        self.assertEqual(
            favorite,
            MusicFavorite(
                guild_id=10,
                slot=1,
                title="재생 중인 노래",
                url="https://youtube.com/watch?v=abc",
                duration=123,
                uploader="업로더",
                thumbnail="https://example.com/thumb.jpg",
            ),
        )

    def test_current_player_without_url_is_not_favorite_snapshot(self):
        player = _Player(
            title="URL 없는 노래",
            webpage_url=None,
            data={"title": "URL 없는 노래"},
        )

        self.assertIsNone(current_player_to_music_favorite(10, player))

    def test_current_player_snapshot_uses_safe_defaults(self):
        player = _Player(
            title=None,
            webpage_url=None,
            data={
                "title": "",
                "webpage_url": "https://youtube.com/watch?v=fallback",
                "duration": "not-a-number",
            },
        )

        favorite = current_player_to_music_favorite(10, player)

        self.assertIsNotNone(favorite)
        assert favorite is not None
        self.assertEqual(favorite.title, "(제목 정보 없음)")
        self.assertEqual(favorite.url, "https://youtube.com/watch?v=fallback")
        self.assertEqual(favorite.duration, 0)

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

    async def test_open_favorite_manager_acknowledges_before_loading_favorites(self):
        cog = MusicCog(_Bot())
        interaction = _Interaction()

        async def load_favorites(guild_id, *, refresh=False):
            self.assertTrue(interaction.response.deferred)
            self.assertEqual(guild_id, 1)
            self.assertTrue(refresh)
            return []

        cog._load_music_favorites = load_favorites

        await cog._open_music_favorite_manager(interaction)

        self.assertTrue(interaction.followup.sent)
        _, kwargs = interaction.followup.sent
        self.assertTrue(kwargs["ephemeral"])
        self.assertIsNotNone(kwargs["view"])


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


class _Bot:
    pass


class _Player:
    def __init__(self, *, title, webpage_url, data):
        self.title = title
        self.webpage_url = webpage_url
        self.data = data


class _Guild:
    id = 1


class _Response:
    def __init__(self):
        self.deferred = False
        self.defer_kwargs = None

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs = kwargs

    async def send_message(self, *args, **kwargs):
        raise AssertionError("favorite manager must use followup after defer")


class _Followup:
    def __init__(self):
        self.sent = None

    async def send(self, *args, **kwargs):
        self.sent = (args, kwargs)
        return object()


class _Interaction:
    def __init__(self):
        self.guild = _Guild()
        self.response = _Response()
        self.followup = _Followup()


if __name__ == "__main__":
    unittest.main()
