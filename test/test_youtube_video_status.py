import unittest

from util.youtube_video_status import fetch_youtube_video_status
from util.youtube_websub import YouTubeVideoStatus


class YouTubeVideoStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_video_status_requests_video_and_classifies_first_item(self):
        youtube = _FakeYouTube(
            {
                "items": [
                    {
                        "id": "video-1",
                        "snippet": {
                            "channelId": "UC_TEST",
                            "title": "테스트 영상",
                            "liveBroadcastContent": "none",
                            "publishedAt": "2026-06-23T00:00:00Z",
                        },
                        "contentDetails": {"duration": "PT10M"},
                    }
                ]
            }
        )

        status = await fetch_youtube_video_status(youtube, "video-1")

        self.assertIsNotNone(status)
        self.assertEqual(status.video_id, "video-1")
        self.assertEqual(status.channel_id, "UC_TEST")
        self.assertEqual(status.title, "테스트 영상")
        self.assertEqual(status.status, YouTubeVideoStatus.UPLOAD)
        self.assertEqual(
            youtube.calls,
            [
                {
                    "part": "snippet,liveStreamingDetails,status,contentDetails",
                    "id": "video-1",
                    "maxResults": 1,
                }
            ],
        )

    async def test_fetch_video_status_returns_none_for_empty_items(self):
        youtube = _FakeYouTube({"items": []})

        status = await fetch_youtube_video_status(youtube, "missing-video")

        self.assertIsNone(status)


class _FakeYouTube:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def videos(self):
        return _FakeVideos(self)


class _FakeVideos:
    def __init__(self, youtube: _FakeYouTube):
        self.youtube = youtube

    def list(self, **kwargs):
        self.youtube.calls.append(kwargs)
        return _FakeRequest(self.youtube.response)


class _FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


if __name__ == "__main__":
    unittest.main()
