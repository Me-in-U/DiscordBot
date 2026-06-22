import unittest
from pathlib import Path

from util.youtube.channel_resolver import (
    YouTubeChannelMetadata,
    extract_youtube_channel_handle,
    is_youtube_channel_id,
    resolve_youtube_channel_input,
)


YOUTUBE_CHANNEL_RESOLVER_PATH = Path("util/youtube/channel_resolver.py")
LEGACY_YOUTUBE_CHANNEL_RESOLVER_PATH = Path("util/youtube_channel_resolver.py")


class FakeYouTubeClient:
    def __init__(self, response, *, search_response=None):
        self.response = response
        self.search_response = search_response
        self.calls = []
        self.resource = None

    def channels(self):
        self.resource = "channels"
        return self

    def search(self):
        self.resource = "search"
        return self

    def list(self, **kwargs):
        kwargs["resource"] = self.resource
        self.calls.append(kwargs)
        return self

    def execute(self):
        if self.resource == "search":
            return self.search_response
        return self.response


class YouTubeChannelResolverTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_channel_resolver_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_CHANNEL_RESOLVER_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_CHANNEL_RESOLVER_PATH.exists())

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

    async def test_search_query_fetches_most_relevant_channel_metadata(self):
        client = FakeYouTubeClient(
            {
                "items": [
                    {
                        "id": "UCabcdefghijklmnopqrstuv",
                        "snippet": {
                            "title": "침착맨 플러스",
                            "customUrl": "@ChimChakMan_Data",
                        },
                    }
                ]
            },
            search_response={
                "items": [
                    {
                        "id": {"channelId": "UCabcdefghijklmnopqrstuv"},
                        "snippet": {"title": "침착맨 플러스"},
                    }
                ]
            },
        )

        result = await resolve_youtube_channel_input(
            "침착맨 플러스",
            youtube_client=client,
        )

        self.assertEqual(
            result,
            YouTubeChannelMetadata(
                channel_id="UCabcdefghijklmnopqrstuv",
                channel_name="침착맨 플러스",
                channel_handle="@ChimChakMan_Data",
            ),
        )
        self.assertEqual(client.calls[0]["resource"], "search")
        self.assertEqual(client.calls[0]["q"], "침착맨 플러스")
        self.assertEqual(client.calls[0]["type"], "channel")
        self.assertEqual(client.calls[0]["maxResults"], 1)
        self.assertEqual(client.calls[1]["resource"], "channels")
        self.assertEqual(client.calls[1]["id"], "UCabcdefghijklmnopqrstuv")

    async def test_raises_when_channel_is_not_found(self):
        client = FakeYouTubeClient({"items": []})

        with self.assertRaisesRegex(ValueError, "유튜브 채널을 찾지 못했습니다"):
            await resolve_youtube_channel_input("@missing", youtube_client=client)


if __name__ == "__main__":
    unittest.main()
