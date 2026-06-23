import unittest
from pathlib import Path


MUSIC_SEARCH_PATH = Path("util/music/search.py")
LEGACY_MUSIC_SEARCH_PATH = Path("util/music_search.py")


class MusicSearchHelperTests(unittest.TestCase):
    def test_search_helper_lives_under_music_package(self):
        self.assertTrue(MUSIC_SEARCH_PATH.exists())
        self.assertFalse(LEGACY_MUSIC_SEARCH_PATH.exists())

    def test_is_http_url_accepts_http_and_https_only(self):
        from util.music.search import is_http_url

        self.assertTrue(is_http_url("https://www.youtube.com/watch?v=1"))
        self.assertTrue(is_http_url("http://example.com"))
        self.assertFalse(is_http_url("  https://example.com"))
        self.assertFalse(is_http_url("not a url"))
        self.assertFalse(is_http_url(""))
        self.assertFalse(is_http_url(None))

    def test_normalize_search_entry_url_prefers_webpage_url_and_expands_relative_watch_url(self):
        from util.music.search import normalize_search_entry_url

        self.assertEqual(
            normalize_search_entry_url(
                {"webpage_url": "/watch?v=abc123", "url": "https://example.com/fallback"}
            ),
            "https://www.youtube.com/watch?v=abc123",
        )

    def test_filter_youtube_watch_entries_keeps_existing_url_predicate_and_limit(self):
        from util.music.search import filter_youtube_watch_entries

        entries = [
            {"url": "https://www.youtube.com/watch?v=1", "title": "one"},
            {"url": "/watch?v=2", "title": "two"},
            {"url": "https://youtu.be/3", "title": "short"},
            {"webpage_url": "https://www.youtube.com/watch?v=4", "title": "webpage only"},
            {"url": None, "title": "none"},
            None,
            {"url": "https://www.youtube.com/watch?v=5", "title": "five"},
        ]

        filtered = filter_youtube_watch_entries(entries, limit=2)

        self.assertEqual([entry["title"] for entry in filtered], ["one", "two"])

    def test_build_search_results_display_formats_embed_content(self):
        from util.music.search import build_search_results_display

        display = build_search_results_display(
            "lofi",
            [
                {"title": "first track"},
                {"title": "second track"},
                {"title": None},
            ],
        )

        self.assertEqual(display.title, "🔍 `lofi` 검색 결과")
        self.assertEqual(
            display.description,
            "1. first track\n2. second track\n3. -",
        )

    def test_build_music_search_action_returns_no_results_message(self):
        from util.music.search import build_music_search_action

        result = build_music_search_action(
            "lofi",
            {"entries": [{"url": "https://youtu.be/nope", "title": "short"}]},
        )

        self.assertEqual(result.user_message, "❌ 검색 결과가 없습니다.")
        self.assertEqual(result.videos, [])
        self.assertIsNone(result.embed_title)
        self.assertIsNone(result.embed_description)

    def test_build_music_search_action_formats_play_search_results(self):
        from util.music.search import build_music_search_action

        result = build_music_search_action(
            "lofi",
            {
                "entries": [
                    {"url": "https://www.youtube.com/watch?v=1", "title": "one"},
                    {"url": "/watch?v=2", "title": "two"},
                    {"url": "https://youtu.be/3", "title": "short"},
                ]
            },
            limit=2,
        )

        self.assertIsNone(result.user_message)
        self.assertEqual([video["title"] for video in result.videos], ["one", "two"])
        self.assertEqual(result.embed_title, "🔍 `lofi` 검색 결과")
        self.assertEqual(result.embed_description, "1. one\n2. two")

    def test_build_music_search_action_formats_favorite_slot_results(self):
        from util.music.search import build_music_search_action

        result = build_music_search_action(
            "lofi",
            {"entries": [{"url": "https://www.youtube.com/watch?v=1", "title": None}]},
            favorite_slot=3,
        )

        self.assertIsNone(result.user_message)
        self.assertEqual(result.embed_title, "⭐ 3번 즐겨찾기에 저장할 음악 선택")
        self.assertEqual(result.embed_description, "1. -")


class MusicSearchExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_music_search_query_adds_ytdlp_search_prefix(self):
        from util.music.search import run_music_search_query

        seen_searches: list[str] = []

        def extractor(search: str):
            seen_searches.append(search)
            return {"entries": [{"url": "https://www.youtube.com/watch?v=1"}]}

        result = await run_music_search_query("lofi", extractor)

        self.assertEqual(seen_searches, ["ytsearch10:lofi"])
        self.assertEqual(
            result,
            {"entries": [{"url": "https://www.youtube.com/watch?v=1"}]},
        )

    async def test_run_music_search_query_preserves_extractor_result_type(self):
        from util.music.search import run_music_search_query

        result = await run_music_search_query("lofi", lambda search: None)

        self.assertIsNone(result)

    async def test_run_music_search_query_accepts_ytdlp_extractor_object(self):
        from util.music.search import run_music_search_query

        class FakeYtdlp:
            def __init__(self):
                self.calls: list[tuple[str, bool]] = []

            def extract_info(self, search: str, *, download: bool):
                self.calls.append((search, download))
                return {"entries": []}

        ytdlp = FakeYtdlp()

        result = await run_music_search_query("lofi", ytdlp)

        self.assertEqual(result, {"entries": []})
        self.assertEqual(ytdlp.calls, [("ytsearch10:lofi", False)])


class MusicSearchFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_music_search_flow_runs_search_and_maps_play_results(self):
        from util.music.search import build_music_search_flow

        def extractor(search: str):
            return {
                "entries": [
                    {"url": "https://www.youtube.com/watch?v=1", "title": search},
                    {"url": "https://youtu.be/2", "title": "ignored"},
                ]
            }

        result = await build_music_search_flow("lofi", extractor)

        self.assertIsNone(result.user_message)
        self.assertEqual([video["title"] for video in result.videos], ["ytsearch10:lofi"])
        self.assertEqual(result.embed_title, "🔍 `lofi` 검색 결과")
        self.assertEqual(result.embed_description, "1. ytsearch10:lofi")

    async def test_build_music_search_flow_preserves_favorite_slot_mapping(self):
        from util.music.search import build_music_search_flow

        class FakeYtdlp:
            def extract_info(self, search: str, *, download: bool):
                return {
                    "entries": [
                        {"url": "https://www.youtube.com/watch?v=1", "title": search}
                    ]
                }

        result = await build_music_search_flow("lofi", FakeYtdlp(), favorite_slot=2)

        self.assertIsNone(result.user_message)
        self.assertEqual(result.embed_title, "⭐ 2번 즐겨찾기에 저장할 음악 선택")
        self.assertEqual(result.embed_description, "1. ytsearch10:lofi")
