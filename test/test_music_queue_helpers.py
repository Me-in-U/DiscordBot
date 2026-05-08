import collections
import random
import unittest

from cogs.music import (
    QueuedTrack,
    build_queue_preview,
    move_queue_track,
    parse_seek_seconds,
    remove_queue_track,
    shuffle_queue,
)


def _queue(*titles: str):
    return collections.deque(QueuedTrack(url=f"https://example.com/{title}", title=title) for title in titles)


class MusicQueueHelperTests(unittest.TestCase):
    def test_parse_seek_seconds_accepts_seconds_and_mmss(self):
        self.assertEqual(parse_seek_seconds("83"), 83)
        self.assertEqual(parse_seek_seconds("1:23"), 83)

    def test_parse_seek_seconds_rejects_invalid_values(self):
        for value in ("", "-1", "1:", "abc", "1:70"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_seek_seconds(value)

    def test_remove_queue_track_uses_one_based_position(self):
        queue = _queue("a", "b", "c")

        removed = remove_queue_track(queue, 2)

        self.assertEqual(removed.title, "b")
        self.assertEqual([track.title for track in queue], ["a", "c"])

    def test_move_queue_track_uses_one_based_positions(self):
        queue = _queue("a", "b", "c", "d")

        moved = move_queue_track(queue, 4, 2)

        self.assertEqual(moved.title, "d")
        self.assertEqual([track.title for track in queue], ["a", "d", "b", "c"])

    def test_shuffle_queue_keeps_same_tracks_but_changes_order(self):
        queue = _queue("a", "b", "c", "d")

        shuffle_queue(queue, random.Random(4))

        self.assertCountEqual([track.title for track in queue], ["a", "b", "c", "d"])
        self.assertNotEqual([track.title for track in queue], ["a", "b", "c", "d"])

    def test_build_queue_preview_uses_first_three_tracks(self):
        queue = _queue("노래1", "노래2", "노래3", "노래4")

        title, preview = build_queue_preview(queue)

        self.assertEqual(title, "대기열(4개)")
        self.assertEqual(preview, "노래1 → 노래2 → 노래3")

    def test_build_queue_preview_truncates_long_titles_to_ten_chars(self):
        queue = _queue("12345678901", "가나다라마바사아자차카")

        title, preview = build_queue_preview(queue)

        self.assertEqual(title, "대기열(2개)")
        self.assertEqual(preview, "1234567890 → 가나다라마바사아자차")


if __name__ == "__main__":
    unittest.main()
