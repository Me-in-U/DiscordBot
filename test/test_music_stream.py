import unittest

from util.music_stream import (
    build_stream_info_from_player_response,
    extract_initial_player_response,
    select_initial_audio_format,
)


class MusicStreamTests(unittest.TestCase):
    def test_extract_initial_player_response_reads_embedded_json(self):
        html = (
            "<script>var ytInitialPlayerResponse = "
            '{"videoDetails":{"title":"song"}}; window.x = 1;</script>'
        )

        response = extract_initial_player_response(html)

        self.assertEqual(response["videoDetails"]["title"], "song")

    def test_extract_initial_player_response_rejects_missing_payload(self):
        with self.assertRaises(ValueError):
            extract_initial_player_response("<html></html>")

    def test_select_initial_audio_format_prefers_highest_average_bitrate_audio(self):
        response = {
            "streamingData": {
                "adaptiveFormats": [
                    {"mimeType": "video/mp4", "averageBitrate": 999, "url": "video"},
                    {"mimeType": "audio/webm", "averageBitrate": 96, "url": "low"},
                    {"mimeType": "audio/mp4", "averageBitrate": 160, "url": "high"},
                ]
            }
        }

        best = select_initial_audio_format(response)

        self.assertEqual(best["url"], "high")

    def test_build_stream_info_uses_video_details_and_best_thumbnail(self):
        response = {
            "streamingData": {
                "adaptiveFormats": [
                    {"mimeType": "audio/webm", "averageBitrate": 96, "url": "audio"}
                ]
            },
            "videoDetails": {
                "title": "song",
                "lengthSeconds": "123",
                "author": "artist",
                "thumbnail": {"thumbnails": [{"url": "video-thumb"}]},
            },
            "microformat": {
                "playerMicroformatRenderer": {
                    "ownerChannelName": "owner",
                    "thumbnail": {
                        "thumbnails": [{"url": "small"}, {"url": "large"}]
                    },
                }
            },
        }

        audio_url, data = build_stream_info_from_player_response(
            response,
            page_url="https://example.com/watch?v=1",
        )

        self.assertEqual(audio_url, "audio")
        self.assertEqual(
            data,
            {
                "title": "song",
                "webpage_url": "https://example.com/watch?v=1",
                "duration": 123,
                "uploader": "artist",
                "thumbnail": "large",
            },
        )


if __name__ == "__main__":
    unittest.main()
