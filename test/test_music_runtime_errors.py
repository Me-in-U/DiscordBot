import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiomysql
from cogs.music import MusicCog
from util.music.favorites import MusicFavoriteSavePayload
from util.music.search import build_music_search_flow, filter_youtube_watch_entries


class MusicRuntimeErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_followup_omits_view_instead_of_passing_none(self):
        cog = MusicCog(object())

        async def strict_send(content, **kwargs):
            self.assertNotIn("view", kwargs)

        interaction = SimpleNamespace(response=SimpleNamespace(is_done=lambda: True),
                                      followup=SimpleNamespace(send=AsyncMock(side_effect=strict_send)))
        await cog._send_ephemeral_response(interaction, "검색 결과가 없습니다.")
        interaction.followup.send.assert_awaited_once()

    async def test_direct_youtube_music_link_is_not_keyword_searched(self):
        url = "https://music.youtube.com/watch?v=abc123"
        searches = []

        def extractor(query):
            searches.append(query)
            return {"webpage_url": url, "title": "저장할 곡"}

        result = await build_music_search_flow(url, extractor, favorite_slot=2)
        self.assertEqual(searches, [url])
        self.assertEqual(result.videos[0]["url"], url)
        self.assertIsNone(result.user_message)

    async def test_search_failure_and_empty_result_are_user_visible(self):
        for result in (None, {"entries": []}):
            response = await build_music_search_flow("검색", lambda _: result)
            self.assertTrue(response.user_message)
            self.assertFalse(response.videos)

        def fail(_):
            raise RuntimeError("upstream unavailable")

        with self.assertLogs("util.music.search", level="WARNING"):
            response = await build_music_search_flow("검색", fail)
        self.assertIn("검색에 실패", response.user_message)

    def test_search_accepts_video_url_variants_and_rejects_external_hosts(self):
        entries = [{"webpage_url": "/watch?v=one"}, {"url": "https://youtu.be/two"},
                   {"id": "three"}, {"url": "https://example.com/watch?v=four"},
                   {"url": "https://www.youtube.com/channel/invalid"}]
        self.assertEqual(len(filter_youtube_watch_entries(entries)), 3)

    async def test_save_failure_is_reported_and_does_not_refresh_panel(self):
        cog = MusicCog(object())
        cog._send_auto_delete = AsyncMock()
        cog._refresh_music_panel_for_favorites = AsyncMock()
        interaction = SimpleNamespace(response=SimpleNamespace(is_done=lambda: True))
        payload = MusicFavoriteSavePayload(guild_id=1, slot=1, title="곡", url="https://youtu.be/one")
        with patch("cogs.music.favorites.save_music_favorite_payload", new_callable=AsyncMock,
                   side_effect=aiomysql.OperationalError(2006, "connection lost")):
            with self.assertLogs("cogs.music", level="WARNING"):
                await cog._save_music_favorite(interaction, payload)
        self.assertIn("저장하지 못했습니다", cog._send_auto_delete.await_args.args[1])
        cog._refresh_music_panel_for_favorites.assert_not_awaited()

    async def test_failed_favorite_reload_keeps_previous_cache(self):
        cog = MusicCog(object())
        cog._favorite_cache[1] = ["saved"]
        with patch("cogs.music.favorites.list_music_favorites", new_callable=AsyncMock,
                   side_effect=TimeoutError()):
            with self.assertLogs("cogs.music", level="WARNING"):
                self.assertEqual(await cog._load_music_favorites(1, refresh=True), ["saved"])
        self.assertEqual(cog._favorite_cache[1], ["saved"])

    async def test_panel_failure_after_save_still_reports_persisted_favorite(self):
        cog = MusicCog(object())
        cog._send_auto_delete = AsyncMock()
        cog._load_music_favorites = AsyncMock(return_value=[])
        cog._refresh_music_panel_for_favorites = AsyncMock(side_effect=OSError('panel unavailable'))
        interaction = SimpleNamespace(response=SimpleNamespace(is_done=lambda: True))
        payload = MusicFavoriteSavePayload(guild_id=1, slot=1, title='곡', url='https://youtu.be/one')
        result = SimpleNamespace(guild_id=1, user_message='저장 완료')
        with patch('cogs.music.favorites.save_music_favorite_payload', new_callable=AsyncMock,
                   return_value=result) as save:
            with self.assertLogs('cogs.music', level='WARNING'):
                await cog._save_music_favorite(interaction, payload)
        save.assert_awaited_once_with(payload)
        cog._send_auto_delete.assert_awaited_once_with(interaction, '저장 완료')

    async def test_progress_edits_wait_fifteen_seconds_between_updates(self):
        voice = SimpleNamespace(channel=SimpleNamespace(members=[1, 2]), is_paused=lambda: False)
        guild = SimpleNamespace(voice_client=voice)
        cog = MusicCog(SimpleNamespace(get_guild=lambda _: guild))
        state = cog._get_state(1)
        state.player = SimpleNamespace(data={'duration': 180})
        cog._make_playing_embed = lambda *args: 'embed'
        cog._build_control_view = AsyncMock(return_value='view')
        cog._edit_msg = AsyncMock()
        with patch('cogs.music.playback.asyncio.sleep', new_callable=AsyncMock,
                   side_effect=asyncio.CancelledError()) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await cog._updater_loop(1)
        cog._edit_msg.assert_awaited_once()
        sleep.assert_awaited_once_with(15)
