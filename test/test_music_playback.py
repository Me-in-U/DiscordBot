import unittest
from types import SimpleNamespace

from cogs.music import MusicCog
from util.music_playback import (
    MusicPlayerPreparationError,
    prepare_music_player,
    prepare_replay_source,
)
from util.music_state import GuildMusicState


class MusicPlaybackTests(unittest.IsolatedAsyncioTestCase):
    def test_build_prepared_playback_start_exposes_source_and_confirmation_message(self):
        from util.music_playback import build_prepared_playback_start

        player = SimpleNamespace(source="audio-source", title="테스트 곡")

        start = build_prepared_playback_start(player, success_prefix="▶ 재생")

        self.assertEqual(start.source, "audio-source")
        self.assertEqual(start.confirmation_message, "▶ 재생: **테스트 곡**")

    async def test_music_cog_start_prepared_playback_updates_state_and_panel(self):
        events = []
        cog = MusicCog(SimpleNamespace(loop="loop"))
        state = GuildMusicState()
        player = SimpleNamespace(source="audio-source", title="테스트 곡")
        playback_start = SimpleNamespace(source="audio-source")

        def cancel_idle(target_state):
            events.append(("cancel_idle", target_state))

        async def build_control_view(guild_id, target_state):
            events.append(("build_control_view", guild_id, target_state.player))
            return "control-view"

        def vc_play(**kwargs):
            events.append(("vc_play", kwargs))

        async def restart_updater(guild_id):
            events.append(("restart_updater", guild_id))

        def make_playing_embed(target_player, guild_id):
            events.append(("make_playing_embed", target_player, guild_id))
            return "embed"

        async def edit_msg(**kwargs):
            events.append(("edit_msg", kwargs))

        cog._cancel_idle_disconnect = cancel_idle
        cog._build_control_view = build_control_view
        cog._vc_play = vc_play
        cog._restart_updater = restart_updater
        cog._make_playing_embed = make_playing_embed
        cog._edit_msg = edit_msg

        await cog._start_prepared_playback(
            guild_id=123,
            state=state,
            player=player,
            playback_start=playback_start,
            started_at=456.0,
        )

        self.assertIs(state.player, player)
        self.assertEqual(state.start_ts, 456.0)
        self.assertEqual(state.control_view, "control-view")
        self.assertEqual(
            events,
            [
                ("cancel_idle", state),
                ("build_control_view", 123, player),
                ("vc_play", {"guild_id": 123, "source": "audio-source"}),
                ("restart_updater", 123),
                ("make_playing_embed", player, 123),
                (
                    "edit_msg",
                    {"state": state, "embed": "embed", "view": "control-view"},
                ),
            ],
        )

    async def test_prepare_music_player_returns_factory_result_and_preserves_args(self):
        calls = []
        player = object()

        async def source_factory(url, *, loop, requester, start_time=None):
            calls.append((url, loop, requester, start_time))
            return player

        result = await prepare_music_player(
            source_factory,
            "https://example.com/watch?v=1",
            loop="loop",
            requester="requester",
            start_time=15,
        )

        self.assertIs(result, player)
        self.assertEqual(
            calls,
            [("https://example.com/watch?v=1", "loop", "requester", 15)],
        )

    async def test_prepare_music_player_maps_ffmpeg_missing_to_brief_message(self):
        async def source_factory(url, *, loop, requester):
            raise FileNotFoundError("ffmpeg.exe")

        with self.assertRaises(MusicPlayerPreparationError) as cm:
            await prepare_music_player(source_factory, "url", loop=None, requester=None)

        failure = cm.exception.failure
        self.assertEqual(failure.user_message, "❌ FFmpeg 실행 파일을 찾을 수 없습니다.")
        self.assertEqual(failure.delete_after, 8.0)
        self.assertEqual(failure.debug_message, "ffmpeg not found")
        self.assertNotIn("ffmpeg.exe", failure.user_message)

    async def test_prepare_music_player_can_include_ffmpeg_guidance(self):
        async def source_factory(url, *, loop, requester):
            raise FileNotFoundError("ffmpeg.exe")

        with self.assertRaises(MusicPlayerPreparationError) as cm:
            await prepare_music_player(
                source_factory,
                "url",
                loop=None,
                requester=None,
                include_ffmpeg_guidance=True,
            )

        failure = cm.exception.failure
        self.assertIn("bin/ffmpeg.exe", failure.user_message)
        self.assertEqual(failure.delete_after, 12.0)

    async def test_prepare_music_player_maps_unexpected_error_to_safe_message(self):
        async def source_factory(url, *, loop, requester):
            raise RuntimeError("raw upstream body")

        with self.assertRaises(MusicPlayerPreparationError) as cm:
            await prepare_music_player(source_factory, "url", loop=None, requester=None)

        failure = cm.exception.failure
        self.assertIn("스트림 URL을 가져오지 못했습니다", failure.user_message)
        self.assertNotIn("raw upstream body", failure.user_message)
        self.assertEqual(failure.delete_after, 10.0)
        self.assertIn("RuntimeError", failure.debug_message)

    async def test_prepare_replay_source_reuses_cached_audio_url(self):
        calls = []
        player = SimpleNamespace(
            audio_url="cached-audio",
            data={"url": "data-audio"},
            webpage_url="https://example.com/watch?v=1",
        )

        def ffmpeg_source_factory(audio_url, **kwargs):
            calls.append((audio_url, kwargs))
            return "new-source"

        async def source_factory(url, *, loop, requester):
            raise AssertionError("refresh should not run")

        result = await prepare_replay_source(
            player,
            source_factory=source_factory,
            ffmpeg_source_factory=ffmpeg_source_factory,
            ffmpeg_options={"options": "-vn"},
            ffmpeg_executable="ffmpeg.exe",
            loop="loop",
        )

        self.assertEqual(result.source, "new-source")
        self.assertIsNone(result.refreshed_player)
        self.assertEqual(
            calls,
            [("cached-audio", {"options": "-vn", "executable": "ffmpeg.exe"})],
        )

    async def test_prepare_replay_source_refreshes_when_cached_source_fails(self):
        calls = []
        refreshed = SimpleNamespace(source="fresh-source", audio_url="fresh-audio")
        player = SimpleNamespace(
            audio_url="stale-audio",
            data={"url": "data-audio"},
            webpage_url="https://example.com/watch?v=1",
        )

        def ffmpeg_source_factory(audio_url, **kwargs):
            raise RuntimeError(f"stale: {audio_url}")

        async def source_factory(url, *, loop, requester):
            calls.append((url, loop, requester))
            return refreshed

        result = await prepare_replay_source(
            player,
            source_factory=source_factory,
            ffmpeg_source_factory=ffmpeg_source_factory,
            ffmpeg_options={},
            ffmpeg_executable="ffmpeg.exe",
            loop="loop",
        )

        self.assertEqual(result.source, "fresh-source")
        self.assertIs(result.refreshed_player, refreshed)
        self.assertEqual(calls, [("https://example.com/watch?v=1", "loop", None)])


if __name__ == "__main__":
    unittest.main()
