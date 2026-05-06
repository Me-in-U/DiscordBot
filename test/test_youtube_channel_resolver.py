import unittest

from util.youtube_channel_resolver import (
    YouTubeChannelMetadata,
    extract_youtube_channel_handle,
    is_youtube_channel_id,
    resolve_youtube_channel_input,
)


class FakeYouTubeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def channels(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        return self.response


class YouTubeChannelResolverTests(unittest.IsolatedAsyncioTestCase):
    def test_detects_channel_id(self):
        self.assertTrue(is_youtube_channel_id("UC1234567890123456789012"))
        self.assertFalse(is_youtube_channel_id("@ChimChakMan_Data"))

    def test_extracts_handle_from_plain_or_url_input(self):
        self.assertEqual(
            extract_youtube_channel_handle("@ChimChakMan_Data"),
            "@ChimChakMan_Data",
        )
        self.assertEqual(
            extract_youtube_channel_handle(
                "https://www.youtube.com/@ChimChakMan_Data/videos"
            ),
            "@ChimChakMan_Data",
        )

    async def test_channel_id_input_fetches_metadata_by_id(self):
        client = FakeYouTubeClient(
            {
                "items": [
                    {
                        "id": "UC1234567890123456789012",
                        "snippet": {
                            "title": "침착맨 플러스",
                            "customUrl": "@ChimChakMan_Data",
                        },
                    }
                ]
            }
        )

        result = await resolve_youtube_channel_input(
            "UC1234567890123456789012",
            youtube_client=client,
        )

        self.assertEqual(
            result,
            YouTubeChannelMetadata(
                channel_id="UC1234567890123456789012",
                channel_name="침착맨 플러스",
                channel_handle="@ChimChakMan_Data",
            ),
        )
        self.assertEqual(client.calls[0]["id"], "UC1234567890123456789012")

    async def test_handle_input_fetches_metadata_by_handle(self):
        client = FakeYouTubeClient(
            {
                "items": [
                    {
                        "id": "UCabcdefghijklmnopqrstuv",
                        "snippet": {
                            "title": "침착맨 원본 박물관",
                            "customUrl": "@ChimChakMan_Data",
                        },
                    }
                ]
            }
        )

        result = await resolve_youtube_channel_input(
            "https://www.youtube.com/@ChimChakMan_Data",
            youtube_client=client,
        )

        self.assertEqual(result.channel_id, "UCabcdefghijklmnopqrstuv")
        self.assertEqual(result.channel_name, "침착맨 원본 박물관")
        self.assertEqual(result.channel_handle, "@ChimChakMan_Data")
        self.assertEqual(client.calls[0]["forHandle"], "@ChimChakMan_Data")

    async def test_raises_when_channel_is_not_found(self):
        client = FakeYouTubeClient({"items": []})

        with self.assertRaisesRegex(ValueError, "유튜브 채널을 찾지 못했습니다"):
            await resolve_youtube_channel_input("@missing", youtube_client=client)


if __name__ == "__main__":
    unittest.main()
