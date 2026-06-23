import unittest

from util.music_queue import QueuedTrack
from util.music_state import (
    GuildMusicState,
    finish_music_track_state,
    reset_music_idle_state,
    reset_music_playback_state,
    start_music_playback_state,
)


class MusicStateTests(unittest.TestCase):
    def test_guild_music_state_uses_independent_queues_and_default_flags(self):
        first = GuildMusicState()
        second = GuildMusicState()

        first.queue.append(QueuedTrack(url="https://example.com/a", title="a"))

        self.assertEqual(len(first.queue), 1)
        self.assertEqual(len(second.queue), 0)
        self.assertIsNone(first.player)
        self.assertEqual(first.start_ts, 0.0)
        self.assertIsNone(first.paused_at)
        self.assertFalse(first.is_loop)
        self.assertFalse(first.is_seeking)
        self.assertFalse(first.is_skipping)
        self.assertFalse(first.is_stopping)

    def test_reset_playback_state_clears_player_queue_loop_and_cancels_updater(self):
        task = _Task()
        state = GuildMusicState(
            player=object(),
            start_ts=123.4,
            paused_at=100.0,
            updater_task=task,
            is_loop=True,
            is_skipping=True,
            is_stopping=True,
        )
        state.queue.append(QueuedTrack(url="https://example.com/a", title="a"))

        reset_music_playback_state(state)

        self.assertIsNone(state.player)
        self.assertEqual(len(state.queue), 0)
        self.assertFalse(state.is_loop)
        self.assertFalse(state.is_skipping)
        self.assertTrue(state.is_stopping)
        self.assertIsNone(state.updater_task)
        self.assertTrue(task.cancelled)

    def test_reset_idle_state_clears_elapsed_and_flags_without_touching_queue(self):
        state = GuildMusicState(
            player=object(),
            start_ts=123.4,
            paused_at=100.0,
            is_loop=True,
            is_skipping=True,
            is_stopping=True,
        )
        state.queue.append(QueuedTrack(url="https://example.com/a", title="a"))

        reset_music_idle_state(state)

        self.assertIsNone(state.player)
        self.assertEqual(state.start_ts, 0.0)
        self.assertIsNone(state.paused_at)
        self.assertFalse(state.is_loop)
        self.assertFalse(state.is_skipping)
        self.assertFalse(state.is_stopping)
        self.assertEqual(len(state.queue), 1)

    def test_start_music_playback_state_sets_current_player_and_play_flags(self):
        player = object()
        state = GuildMusicState(
            player=object(),
            start_ts=1.0,
            paused_at=2.0,
            is_skipping=True,
            is_stopping=True,
        )

        start_music_playback_state(state, player, started_at=123.4)

        self.assertIs(state.player, player)
        self.assertEqual(state.start_ts, 123.4)
        self.assertIsNone(state.paused_at)
        self.assertFalse(state.is_skipping)
        self.assertFalse(state.is_stopping)

    def test_finish_music_track_state_cancels_updater_and_marks_end_time(self):
        task = _Task()
        state = GuildMusicState(
            player=object(),
            start_ts=1.0,
            paused_at=2.0,
            updater_task=task,
        )

        finish_music_track_state(state, ended_at=321.0)

        self.assertEqual(state.start_ts, 321.0)
        self.assertIsNone(state.paused_at)
        self.assertTrue(task.cancelled)


class _Task:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


if __name__ == "__main__":
    unittest.main()
