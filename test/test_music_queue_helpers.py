import collections
import random
import unittest
from types import SimpleNamespace

from cogs.music import (
    QueuedTrack,
    build_queue_preview,
    move_queue_track,
    parse_seek_seconds,
    remove_queue_track,
    shuffle_queue,
)
from util import music_queue
from util.music_queue import (
    apply_queue_track_metadata,
    build_queue_display,
    extract_queue_track_metadata,
)


def _queue(*titles: str):
    return collections.deque(QueuedTrack(url=f"https://example.com/{title}", title=title) for title in titles)


class MusicQueueHelperTests(unittest.TestCase):
    def test_queue_helpers_are_available_from_util_module(self):
        queue = collections.deque(
            [
                music_queue.QueuedTrack(url="https://example.com/a", title="a"),
                music_queue.QueuedTrack(url="https://example.com/b", title="b"),
            ]
        )

        removed = music_queue.remove_queue_track(queue, 1)

        self.assertEqual(removed.title, "a")
        self.assertEqual([track.title for track in queue], ["b"])

    def test_track_title_helper_is_available_to_music_cog_module(self):
        from cogs.music import _track_title

        self.assertEqual(
            _track_title(QueuedTrack(url="https://example.com/fallback", title="노래")),
            "노래",
        )

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
        self.assertEqual(preview, "`1` 노래1\n`2` 노래2\n`3` 노래3\n+ 1곡 더")

    def test_build_queue_preview_truncates_long_titles_to_twenty_eight_chars(self):
        queue = _queue(
            "12345678901234567890123456789",
            "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허끝",
        )

        title, preview = build_queue_preview(queue)

        self.assertEqual(title, "대기열(2개)")
        self.assertEqual(
            preview,
            "`1` 1234567890123456789012345678…\n"
            "`2` 가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허…",
        )

    def test_build_queue_display_includes_current_track_and_limits_visible_tracks(self):
        queue = collections.deque(
            [
                QueuedTrack(
                    url="https://example.com/1",
                    title="첫곡",
                    duration=123,
                    webpage_url="https://example.com/watch/1",
                    uploader="업로더1",
                    requester=SimpleNamespace(id=42),
                ),
                QueuedTrack(
                    url="https://example.com/2",
                    title="둘째곡",
                    uploader="업로더2",
                ),
                QueuedTrack(url="https://example.com/3", title="셋째곡"),
            ]
        )
        player = SimpleNamespace(
            title="현재곡",
            webpage_url="https://example.com/current",
            requester=SimpleNamespace(id=99),
            data={"duration": 83, "uploader": "현재업로더"},
        )

        display = build_queue_display(
            queue,
            player=player,
            max_display=2,
            unknown="알 수 없음",
        )

        self.assertEqual(display.title, "대기열 - 3개의 곡")
        self.assertEqual(
            display.description,
            "**현재 재생 중.** \n"
            "[현재곡](https://example.com/current)(01:23)"
            "(현재업로더) - 신청자: <@99>\n"
            "\n"
            "1. [첫곡](https://example.com/watch/1)(02:03)"
            "(업로더1) - 신청자: <@42>\n"
            "2. [둘째곡](https://example.com/2)(업로더2) - 신청자: 알 수 없음\n"
            "... 외 1곡",
        )

    def test_build_queue_display_omits_current_track_when_player_is_missing(self):
        queue = collections.deque([QueuedTrack(url="https://example.com/1")])

        display = build_queue_display(queue, player=None, unknown="알 수 없음")

        self.assertEqual(display.title, "대기열 - 1개의 곡")
        self.assertEqual(
            display.description,
            "1. [https://example.com/1](https://example.com/1)"
            "(알 수 없음) - 신청자: 알 수 없음",
        )

    def test_enqueue_url_track_appends_lightweight_track_and_returns_it(self):
        from util.music_queue import enqueue_url_track

        requester = SimpleNamespace(id=123)
        queue = collections.deque()

        track = enqueue_url_track(queue, "https://example.com/video", requester)

        self.assertIs(track, queue[0])
        self.assertEqual(track.url, "https://example.com/video")
        self.assertIs(track.requester, requester)
        self.assertIsNone(track.title)

    def test_enqueue_search_entry_track_preserves_search_metadata(self):
        from util.music_queue import enqueue_search_entry_track

        requester = SimpleNamespace(id=123)
        queue = collections.deque()
        entry = {
            "title": "검색 결과 곡",
            "duration": "125",
            "webpage_url": "https://www.youtube.com/watch?v=abc",
            "uploader": "",
            "channel": "채널명",
            "thumbnails": [
                {"url": "https://example.com/low.jpg"},
                {"url": "https://example.com/high.jpg"},
            ],
        }

        track = enqueue_search_entry_track(
            queue,
            entry,
            url="https://www.youtube.com/watch?v=abc",
            requester=requester,
        )

        self.assertIs(track, queue[0])
        self.assertEqual(track.url, "https://www.youtube.com/watch?v=abc")
        self.assertIs(track.requester, requester)
        self.assertEqual(track.title, "검색 결과 곡")
        self.assertEqual(track.duration, 125)
        self.assertEqual(track.webpage_url, "https://www.youtube.com/watch?v=abc")
        self.assertEqual(track.uploader, "채널명")
        self.assertEqual(track.thumbnail, "https://example.com/high.jpg")

    def test_apply_queue_track_metadata_uses_single_entry_and_thumbnail_fallback(self):
        track = QueuedTrack(
            url="https://example.com/fallback",
            title="기존 제목",
            duration=10,
            webpage_url="https://example.com/old",
            uploader="기존 업로더",
            thumbnail="https://example.com/old.jpg",
        )
        metadata = {
            "entries": [
                {
                    "title": "추출 제목",
                    "duration": "125",
                    "webpage_url": "https://example.com/watch",
                    "uploader": "추출 업로더",
                    "thumbnails": [
                        {"url": "https://example.com/low.jpg"},
                        {"url": "https://example.com/high.jpg"},
                    ],
                }
            ]
        }

        result = apply_queue_track_metadata(track, metadata)

        self.assertIs(result, track)
        self.assertEqual(track.title, "추출 제목")
        self.assertEqual(track.duration, 125)
        self.assertEqual(track.webpage_url, "https://example.com/watch")
        self.assertEqual(track.uploader, "추출 업로더")
        self.assertEqual(track.thumbnail, "https://example.com/high.jpg")

    def test_extract_queue_track_metadata_returns_dict_result(self):
        def extractor(url: str):
            return {"title": f"title:{url}"}

        self.assertEqual(
            extract_queue_track_metadata("abc", extractor),
            {"title": "title:abc"},
        )

    def test_extract_queue_track_metadata_returns_none_for_extraction_errors(self):
        def extractor(url: str):
            raise ValueError("bad metadata")

        self.assertIsNone(extract_queue_track_metadata("abc", extractor))


if __name__ == "__main__":
    unittest.main()
