import collections
import unittest

from util.music_queue import QueuedTrack
from util.music_queue_actions import (
    clear_queue_action,
    move_queue_action,
    remove_queue_action,
    shuffle_queue_action,
)


def _queue(*titles: str):
    return collections.deque(
        QueuedTrack(url=f"https://example.com/{title}", title=title)
        for title in titles
    )


class MusicQueueActionTests(unittest.TestCase):
    def test_remove_queue_action_mutates_queue_and_returns_user_message(self):
        queue = _queue("첫곡", "둘째곡", "셋째곡")

        result = remove_queue_action(queue, 2)

        self.assertEqual([track.title for track in queue], ["첫곡", "셋째곡"])
        self.assertEqual(
            result.user_message,
            "🗑️ 대기열에서 **둘째곡** 항목을 삭제했습니다.",
        )

    def test_clear_queue_action_requires_non_empty_queue(self):
        queue = _queue()

        with self.assertRaisesRegex(ValueError, "대기열이 비어있습니다"):
            clear_queue_action(queue)

    def test_clear_queue_action_clears_and_reports_count(self):
        queue = _queue("a", "b", "c")

        result = clear_queue_action(queue)

        self.assertEqual(list(queue), [])
        self.assertEqual(result.user_message, "🧹 대기열 3곡을 비웠습니다.")

    def test_move_queue_action_mutates_queue_and_returns_user_message(self):
        queue = _queue("a", "b", "c")

        result = move_queue_action(queue, 3, 1)

        self.assertEqual([track.title for track in queue], ["c", "a", "b"])
        self.assertEqual(
            result.user_message,
            "↕️ **c** 항목을 1번으로 이동했습니다.",
        )

    def test_shuffle_queue_action_requires_at_least_two_tracks(self):
        queue = _queue("a")

        with self.assertRaisesRegex(ValueError, "섞을 대기열이 2곡 이상 필요합니다"):
            shuffle_queue_action(queue)

    def test_shuffle_queue_action_returns_user_message(self):
        queue = _queue("a", "b", "c")

        result = shuffle_queue_action(queue)

        self.assertCountEqual([track.title for track in queue], ["a", "b", "c"])
        self.assertEqual(result.user_message, "🔀 대기열을 섞었습니다.")


if __name__ == "__main__":
    unittest.main()
