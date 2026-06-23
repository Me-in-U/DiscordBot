import os
import unittest
import warnings
from unittest.mock import AsyncMock, patch

os.environ.setdefault("OPENAI_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
warnings.simplefilter("ignore", DeprecationWarning)


class YouTubeProcessorModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_youtube_link_wraps_failures_without_raw_exception(self):
        import func.youtube_processor as youtube_processor

        with patch(
            "func.youtube_processor.process_youtube_video_link",
            side_effect=ValueError("raw-secret"),
        ):
            with self.assertRaises(youtube_processor.YouTubeSummaryError) as captured:
                await youtube_processor.process_youtube_link("https://youtu.be/test-video")

        self.assertIsInstance(captured.exception.__cause__, ValueError)
        self.assertNotIn("raw-secret", str(captured.exception))


class YouTubeProcessorCompatibilityTests(unittest.TestCase):
    def test_legacy_youtube_summary_reexports_processor_entrypoints(self):
        import func.youtube_processor as youtube_processor
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import func.youtube_summary as youtube_summary

        self.assertIs(youtube_summary.YouTubeSummaryError, youtube_processor.YouTubeSummaryError)
        self.assertIs(youtube_summary.process_youtube_link, youtube_processor.process_youtube_link)
        self.assertIs(
            youtube_summary.process_youtube_video_link,
            youtube_processor.process_youtube_video_link,
        )
        self.assertIs(
            youtube_summary.process_youtube_post_link,
            youtube_processor.process_youtube_post_link,
        )
        self.assertIs(youtube_summary.fetch_youtube_post, youtube_processor.fetch_youtube_post)


class YouTubeProcessorPostTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_youtube_post_normalizes_url_before_fetching(self):
        import func.youtube_processor as youtube_processor
        from func.youtube_post import YouTubePostInfo

        captured = {}
        expected_post = YouTubePostInfo(post_id="UgkxTest", url="https://youtube.com/post/UgkxTest")

        class FakeResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def raise_for_status(self):
                return None

            async def text(self):
                return "<html></html>"

        class FakeSession:
            def __init__(self, **_kwargs):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def get(self, url):
                captured["url"] = url
                return FakeResponse()

        with patch("func.youtube_processor.aiohttp.ClientSession", FakeSession):
            with patch(
                "func.youtube_processor.parse_youtube_post_html",
                return_value=expected_post,
            ) as parse_post:
                result = await youtube_processor.fetch_youtube_post(
                    "http://youtube.com/post/UgkxTest"
                )

        self.assertIs(result, expected_post)
        self.assertEqual(captured["url"], "https://youtube.com/post/UgkxTest")
        parse_post.assert_called_once_with(
            "<html></html>",
            "https://youtube.com/post/UgkxTest",
        )


class YouTubeProcessorVideoTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_youtube_video_link_keeps_summary_when_comments_fail(self):
        import func.youtube_processor as youtube_processor

        with patch("func.youtube_processor.extract_video_id", return_value="video-id"):
            with patch("func.youtube_processor.is_live_video", return_value=False):
                with patch("func.youtube_processor.download_youtube_subtitles", return_value=""):
                    with patch("func.youtube_processor.youtube_to_mp3", new=AsyncMock()):
                        with patch(
                            "func.youtube_processor.speech_to_text",
                            new=AsyncMock(return_value="STT 텍스트"),
                        ):
                            with patch(
                                "func.youtube_processor.summarize_text_with_gpt",
                                new=AsyncMock(return_value="영상 요약"),
                            ):
                                with patch(
                                    "func.youtube_processor.fetch_youtube_comments",
                                    side_effect=youtube_processor.YouTubeApiError(
                                        "comment failure"
                                    ),
                                ):
                                    with self.assertLogs(
                                        "func.youtube_processor",
                                        level="WARNING",
                                    ):
                                        result = (
                                            await youtube_processor.process_youtube_video_link(
                                                "https://youtu.be/test-video"
                                            )
                                        )

        self.assertEqual(result, "영상 요약")


if __name__ == "__main__":
    unittest.main()
