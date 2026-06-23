import unittest

from util.music_playback_actions import (
    begin_url_play_action,
    begin_stop_playback_action,
    begin_seek_playback_action,
    complete_seek_playback_action,
    fail_seek_playback_action,
    pause_playback_action,
    resume_playback_action,
    skip_playback_action,
    toggle_loop_action,
    validate_seek_playback_action,
)
from util.music_state import GuildMusicState


class MusicPlaybackActionTests(unittest.TestCase):
    def test_pause_playback_action_sets_paused_at_and_returns_elapsed(self):
        state = GuildMusicState(start_ts=100.2)

        result = pause_playback_action(state, paused_at=142.8)

        self.assertEqual(state.paused_at, 142.8)
        self.assertEqual(result.elapsed, 42)
        self.assertEqual(result.user_message, "⏸️ 일시정지했습니다.")

    def test_resume_playback_action_shifts_start_time_by_pause_duration(self):
        state = GuildMusicState(start_ts=100.0, paused_at=130.0)

        result = resume_playback_action(state, resumed_at=160.0)

        self.assertEqual(state.start_ts, 130.0)
        self.assertIsNone(state.paused_at)
        self.assertEqual(result.elapsed, 30)
        self.assertEqual(result.user_message, "▶️ 다시 재생합니다.")

    def test_resume_playback_action_handles_missing_paused_at(self):
        state = GuildMusicState(start_ts=100.0, paused_at=None)

        result = resume_playback_action(state, resumed_at=125.0)

        self.assertEqual(state.start_ts, 100.0)
        self.assertIsNone(state.paused_at)
        self.assertEqual(result.elapsed, 25)

    def test_begin_stop_playback_action_marks_stopping_and_returns_message(self):
        state = GuildMusicState(is_stopping=False)

        result = begin_stop_playback_action(state)

        self.assertTrue(state.is_stopping)
        self.assertEqual(result.user_message, "⏹️ 정지하고 나갑니다.")

    def test_begin_url_play_action_queues_url_when_voice_is_active(self):
        state = GuildMusicState()
        requester = object()

        result = begin_url_play_action(
            state,
            url="https://example.com/watch?v=1",
            requester=requester,
            is_active=True,
        )

        self.assertFalse(result.should_prepare)
        self.assertEqual(result.user_message, "▶ **대기열에 추가되었습니다.**")
        self.assertIsNotNone(result.queued_track)
        self.assertEqual(result.queue_size, 1)
        self.assertEqual(len(state.queue), 1)
        self.assertIs(state.queue[0], result.queued_track)
        self.assertEqual(state.queue[0].url, "https://example.com/watch?v=1")
        self.assertIs(state.queue[0].requester, requester)

    def test_begin_url_play_action_allows_immediate_prepare_when_voice_is_idle(self):
        state = GuildMusicState()

        result = begin_url_play_action(
            state,
            url="https://example.com/watch?v=1",
            requester=object(),
            is_active=False,
        )

        self.assertTrue(result.should_prepare)
        self.assertIsNone(result.user_message)
        self.assertIsNone(result.queued_track)
        self.assertEqual(result.queue_size, 0)
        self.assertEqual(len(state.queue), 0)

    def test_skip_playback_action_returns_skip_message_when_loop_is_off(self):
        state = GuildMusicState(is_loop=False, is_skipping=False)

        result = skip_playback_action(state)

        self.assertFalse(state.is_skipping)
        self.assertFalse(result.is_loop)
        self.assertEqual(result.user_message, "⏭️ 스킵합니다.")

    def test_skip_playback_action_returns_restart_message_when_loop_is_on(self):
        state = GuildMusicState(is_loop=True, is_skipping=False)

        result = skip_playback_action(state)

        self.assertFalse(state.is_skipping)
        self.assertTrue(result.is_loop)
        self.assertEqual(result.user_message, "🔁 반복 모드: 처음부터 재생합니다.")

    def test_validate_seek_playback_action_rejects_target_at_or_after_duration(self):
        state = GuildMusicState()
        state.player = type("Player", (), {"data": {"duration": 180}})()

        result = validate_seek_playback_action(state, seconds=180)

        self.assertIsNotNone(result)
        self.assertEqual(
            result.user_message,
            "❌ 이동할 시간은 곡 길이(180초)보다 작아야 합니다.",
        )
        self.assertEqual(result.delete_after, 6.0)

    def test_validate_seek_playback_action_allows_unknown_or_larger_duration(self):
        state = GuildMusicState()
        state.player = type("Player", (), {"data": {"duration": 0}})()

        self.assertIsNone(validate_seek_playback_action(state, seconds=999))

    def test_begin_seek_playback_action_marks_state_as_seeking(self):
        state = GuildMusicState(is_seeking=False)

        begin_seek_playback_action(state)

        self.assertTrue(state.is_seeking)

    def test_complete_seek_playback_action_updates_player_and_timeline(self):
        state = GuildMusicState(is_seeking=True, start_ts=100.0, paused_at=125.0)
        player = object()

        result = complete_seek_playback_action(
            state,
            player,
            seconds=42,
            started_at=200.0,
        )

        self.assertIs(state.player, player)
        self.assertEqual(state.start_ts, 158.0)
        self.assertIsNone(state.paused_at)
        self.assertFalse(state.is_seeking)
        self.assertEqual(result.elapsed, 42)
        self.assertEqual(result.user_message, "⏩ 42초 지점으로 이동했습니다.")

    def test_fail_seek_playback_action_clears_seeking_and_returns_safe_message(self):
        state = GuildMusicState(is_seeking=True)

        result = fail_seek_playback_action(state)

        self.assertFalse(state.is_seeking)
        self.assertEqual(result.user_message, "❌ 구간 이동 중 오류가 발생했습니다.")
        self.assertEqual(result.delete_after, 6.0)

    def test_toggle_loop_action_toggles_state_and_returns_user_message(self):
        state = GuildMusicState(is_loop=False)

        first = toggle_loop_action(state)
        second = toggle_loop_action(state)

        self.assertTrue(first.is_loop)
        self.assertEqual(first.user_message, "🔁 반복 모드 켜짐")
        self.assertFalse(second.is_loop)
        self.assertEqual(second.user_message, "🔁 반복 모드 꺼짐")


if __name__ == "__main__":
    unittest.main()
