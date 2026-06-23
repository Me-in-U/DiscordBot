import unittest


class MusicExtractorHelperTests(unittest.TestCase):
    def test_resolve_search_result_url_prefers_webpage_url(self):
        from util.music_extractor import resolve_search_result_url

        info = {
            "entries": [
                {
                    "webpage_url": "https://www.youtube.com/watch?v=webpage",
                    "url": "https://short.example/video",
                    "id": "fallback-id",
                }
            ]
        }

        self.assertEqual(
            resolve_search_result_url(info),
            "https://www.youtube.com/watch?v=webpage",
        )

    def test_resolve_search_result_url_uses_url_then_watch_id_fallback(self):
        from util.music_extractor import resolve_search_result_url

        self.assertEqual(
            resolve_search_result_url({"entries": [{"url": "https://example.com/u"}]}),
            "https://example.com/u",
        )
        self.assertEqual(
            resolve_search_result_url({"entries": [{"id": "abc123"}]}),
            "https://www.youtube.com/watch?v=abc123",
        )

    def test_resolve_search_result_url_raises_for_missing_result_or_url(self):
        from util.music_extractor import resolve_search_result_url

        with self.assertRaisesRegex(ValueError, "검색 결과가 없습니다."):
            resolve_search_result_url({"entries": []})

        with self.assertRaisesRegex(ValueError, "검색 결과 URL이 없습니다."):
            resolve_search_result_url({"entries": [{"title": "no url"}]})

    def test_select_yt_dlp_entry_prefers_entry_with_formats(self):
        from util.music_extractor import select_yt_dlp_entry

        entry_without_formats = {"title": "first"}
        entry_with_formats = {"title": "second", "formats": [{"url": "audio"}]}

        self.assertIs(
            select_yt_dlp_entry(
                {"entries": [entry_without_formats, entry_with_formats]}
            ),
            entry_with_formats,
        )

    def test_select_yt_dlp_entry_falls_back_to_first_non_empty_entry(self):
        from util.music_extractor import select_yt_dlp_entry

        first_entry = {"title": "first"}
        second_entry = {"title": "second"}

        self.assertIs(
            select_yt_dlp_entry({"entries": [None, first_entry, second_entry]}),
            first_entry,
        )

    def test_select_yt_dlp_entry_returns_original_when_no_entries(self):
        from util.music_extractor import select_yt_dlp_entry

        original_without_entries = {"title": "single"}
        original_with_empty_entries = {"entries": []}

        self.assertIs(
            select_yt_dlp_entry(original_without_entries),
            original_without_entries,
        )
        self.assertIs(
            select_yt_dlp_entry(original_with_empty_entries),
            original_with_empty_entries,
        )

    def test_select_best_audio_format_prefers_strict_audio_candidates(self):
        from util.music_extractor import select_best_audio_format

        formats = [
            {"url": "https://example.com/video", "vcodec": "avc1", "abr": 320},
            {
                "url": "https://example.com/strict-low",
                "audio_ext": "m4a",
                "acodec": "mp4a",
                "abr": 96,
            },
            {
                "url": "https://example.com/strict-high",
                "audio_ext": "webm",
                "acodec": "opus",
                "abr": 128,
            },
        ]

        best = select_best_audio_format(formats)

        self.assertEqual(best["url"], "https://example.com/strict-high")

    def test_select_best_audio_format_uses_loose_audio_when_strict_is_absent(self):
        from util.music_extractor import select_best_audio_format

        formats = [
            {"url": "https://example.com/video", "vcodec": "avc1", "abr": 320},
            {
                "url": "https://example.com/loose",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 80,
            },
        ]

        best = select_best_audio_format(formats)

        self.assertEqual(best["url"], "https://example.com/loose")

    def test_select_best_audio_format_falls_back_to_highest_rate_candidate(self):
        from util.music_extractor import select_best_audio_format

        formats = [
            {"url": "https://example.com/low", "vcodec": "avc1", "tbr": 120},
            {"url": "https://example.com/high", "vcodec": "avc1", "tbr": 240},
        ]

        best = select_best_audio_format(formats)

        self.assertEqual(best["url"], "https://example.com/high")

    def test_select_best_audio_format_returns_none_for_empty_formats(self):
        from util.music_extractor import select_best_audio_format

        self.assertIsNone(select_best_audio_format([]))
