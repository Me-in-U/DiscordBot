import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_dlp.utils import DownloadError

from func import youtube_media


class YouTubeMediaTests(unittest.TestCase):
    def test_build_headers_str_uses_crlf_between_headers(self):
        self.assertEqual(
            youtube_media.build_headers_str({"User-Agent": "Bot", "Accept": "text/html"}),
            "User-Agent: Bot\r\nAccept: text/html\r\n",
        )

    def test_subtitles_allow_video_at_duration_limit(self):
        url = "https://youtu.be/test-video"
        with tempfile.TemporaryDirectory() as workspace, patch.object(
            youtube_media, "YoutubeDL"
        ) as youtube_dl:
            def download(_urls):
                options = youtube_dl.call_args.args[0]
                options["match_filter"]({"duration": 1800}, incomplete=False)
                Path(workspace, "youtube_subtitles.ko.vtt").write_text(
                    "WEBVTT\n", encoding="utf-8"
                )

            youtube_dl.return_value.__enter__.return_value.download.side_effect = download
            subtitle_path = youtube_media.download_youtube_subtitles(url, output_dir=workspace)

        self.assertEqual(Path(subtitle_path).name, "youtube_subtitles.ko.vtt")
        youtube_dl.assert_called_once()


class YouTubeFfmpegFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_ffmpeg_fallback_checks_video_duration(self):
        url = "https://youtu.be/test-video"
        for duration in (1800, 1801):
            with self.subTest(duration=duration), tempfile.TemporaryDirectory() as workspace:
                output = Path(workspace, "audio.mp3")
                with (
                    patch.object(youtube_media, "YoutubeDL", side_effect=DownloadError("unavailable")),
                    patch.object(
                        youtube_media,
                        "fetch_stream_info",
                        return_value=("https://example.com/audio", {"duration": duration}),
                    ),
                    patch.object(youtube_media.subprocess, "run") as ffmpeg,
                    self.assertLogs(youtube_media.__name__, level="WARNING") as logs,
                ):
                    if duration == 1800:
                        ffmpeg.side_effect = lambda *args, **kwargs: output.touch()
                        await youtube_media.youtube_to_mp3(url, output_path=output)
                        ffmpeg.assert_called_once()
                        self.assertTrue(output.exists())
                    else:
                        with self.assertRaisesRegex(
                            youtube_media.MediaLimitError, "30분 이하 영상만 요약할 수 있습니다."
                        ):
                            await youtube_media.youtube_to_mp3(url, output_path=output)
                        ffmpeg.assert_not_called()
                        self.assertFalse(output.exists())

                self.assertEqual(len(logs.records), 1)
                self.assertIs(logs.records[0].exc_info[0], DownloadError)


if __name__ == "__main__":
    unittest.main()
