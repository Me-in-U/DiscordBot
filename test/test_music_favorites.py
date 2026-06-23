import unittest

from cogs.music import GuildMusicState, MusicCog, MusicControlView, MusicHelperView
from util.music_favorites import (
    MusicFavorite,
    MusicFavoriteManagerSelectionAction,
    MusicFavoritePlayActionResult,
    MusicFavoriteSavePayload,
    build_music_favorite_manager_selection_action,
    build_music_favorite_button_label,
    build_music_favorite_play_action,
    build_music_favorite_save_payload,
    current_player_to_music_favorite,
    music_favorite_to_save_payload,
    search_entry_to_music_favorite_save_payload,
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

    def test_music_favorite_save_payload_normalizes_values_and_message(self):
        payload = build_music_favorite_save_payload(
            guild_id=10,
            slot=2,
            title="  저장할 노래  ",
            url="  https://youtube.com/watch?v=abc  ",
            duration="125",
            uploader="업로더",
            thumbnail="https://example.com/thumb.jpg",
            updated_by=99,
        )

        self.assertEqual(
            payload,
            MusicFavoriteSavePayload(
                guild_id=10,
                slot=2,
                title="저장할 노래",
                url="https://youtube.com/watch?v=abc",
                duration=125,
                uploader="업로더",
                thumbnail="https://example.com/thumb.jpg",
                updated_by=99,
            ),
        )
        self.assertEqual(
            payload.user_message,
            "⭐ 2번 즐겨찾기에 **저장할 노래** 저장했습니다.",
        )

    def test_music_favorite_save_payload_rejects_missing_url(self):
        with self.assertRaisesRegex(ValueError, "즐겨찾기에 저장할 URL이 없습니다"):
            build_music_favorite_save_payload(
                guild_id=10,
                slot=1,
                title="URL 없음",
                url=" ",
            )

    def test_search_entry_to_music_favorite_save_payload_extracts_metadata(self):
        payload = search_entry_to_music_favorite_save_payload(
            guild_id=10,
            slot=3,
            entry={
                "title": "",
                "duration": "not-a-number",
                "webpage_url": "/watch?v=abc123",
                "uploader": "",
                "channel": "채널명",
                "thumbnails": [
                    {"url": "https://example.com/low.jpg"},
                    {"url": "https://example.com/high.jpg"},
                ],
            },
            updated_by=99,
        )

        self.assertEqual(payload.guild_id, 10)
        self.assertEqual(payload.slot, 3)
        self.assertEqual(payload.title, "(제목 정보 없음)")
        self.assertEqual(payload.url, "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(payload.duration, 0)
        self.assertEqual(payload.uploader, "채널명")
        self.assertEqual(payload.thumbnail, "https://example.com/high.jpg")
        self.assertEqual(payload.updated_by, 99)

    def test_music_favorite_to_save_payload_overrides_slot_and_updater(self):
        favorite = MusicFavorite(
            guild_id=10,
            slot=1,
            title="현재곡",
            url="https://youtube.com/watch?v=abc",
            duration=125,
            uploader="업로더",
            thumbnail="https://example.com/thumb.jpg",
        )

        payload = music_favorite_to_save_payload(favorite, slot=5, updated_by=99)

        self.assertEqual(
            payload,
            MusicFavoriteSavePayload(
                guild_id=10,
                slot=5,
                title="현재곡",
                url="https://youtube.com/watch?v=abc",
                duration=125,
                uploader="업로더",
                thumbnail="https://example.com/thumb.jpg",
                updated_by=99,
            ),
        )

    def test_music_favorite_play_action_returns_empty_slot_message(self):
        result = build_music_favorite_play_action(slot=2, favorite=None)

        self.assertEqual(
            result,
            MusicFavoritePlayActionResult(
                slot=2,
                should_play=False,
                user_message="❌ 2번 즐겨찾기가 비어있습니다.",
            ),
        )

    def test_music_favorite_play_action_returns_url_and_prefix(self):
        favorite = MusicFavorite(
            guild_id=10,
            slot=2,
            title="저장된 노래",
            url="https://youtube.com/watch?v=abc",
        )

        result = build_music_favorite_play_action(slot=2, favorite=favorite)

        self.assertEqual(
            result,
            MusicFavoritePlayActionResult(
                slot=2,
                should_play=True,
                url="https://youtube.com/watch?v=abc",
                success_prefix="⭐ 즐겨찾기 재생",
            ),
        )

    def test_music_favorite_play_action_validates_slot(self):
        with self.assertRaisesRegex(ValueError, "즐겨찾기 번호는 1~5"):
            build_music_favorite_play_action(slot=0, favorite=None)

    def test_music_favorite_manager_selection_action_normalizes_slot(self):
        result = build_music_favorite_manager_selection_action("3")

        self.assertEqual(
            result,
            MusicFavoriteManagerSelectionAction(
                selected_slot=3,
                selected_value="3",
                status_text="저장/수정할 즐겨찾기 슬롯: **3번**",
            ),
        )

    def test_music_favorite_manager_selection_action_marks_default_option(self):
        result = build_music_favorite_manager_selection_action(4)

        self.assertFalse(result.is_default_value("3"))
        self.assertTrue(result.is_default_value("4"))

    def test_music_favorite_manager_selection_action_validates_slot(self):
        with self.assertRaisesRegex(ValueError, "즐겨찾기 번호는 1~5"):
            build_music_favorite_manager_selection_action("6")

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
