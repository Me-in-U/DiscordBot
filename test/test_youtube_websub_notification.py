import unittest
from pathlib import Path

from util.youtube.websub_notification import handle_youtube_websub_notification
from util.youtube_subscriptions import YouTubeSubscription


YOUTUBE_WEBSUB_NOTIFICATION_PATH = Path("util/youtube/websub_notification.py")
LEGACY_YOUTUBE_WEBSUB_NOTIFICATION_PATH = Path("util/youtube_websub_notification.py")


SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>VIDEO123</yt:videoId>
    <yt:channelId>UC_MATCHED</yt:channelId>
    <title>테스트 영상</title>
    <published>2026-06-23T00:00:00+00:00</published>
    <updated>2026-06-23T00:01:00+00:00</updated>
  </entry>
  <entry>
    <yt:videoId>VIDEO_IGNORED</yt:videoId>
    <yt:channelId>UC_IGNORED</yt:channelId>
    <title>무시 영상</title>
    <published>2026-06-23T00:00:00+00:00</published>
    <updated>2026-06-23T00:01:00+00:00</updated>
  </entry>
</feed>
"""


def _subscription(**overrides) -> YouTubeSubscription:
    data = {
        "id": 1,
        "guild_id": 10,
        "channel_name": "채널",
        "channel_id": "UC_MATCHED",
        "channel_handle": None,
        "source_input": "UC_MATCHED",
        "websub_subscribed_at": None,
        "websub_lease_seconds": None,
        "pending_videos": {},
        "notified_video_ids": [],
        "live_alert_enabled": True,
        "upload_alert_enabled": False,
        "upload_alert_enabled_at": None,
        "notified_upload_video_ids": [],
        "community_alert_enabled": False,
        "notified_community_post_ids": [],
    }
    data.update(overrides)
    return YouTubeSubscription(**data)


class YouTubeWebSubNotificationTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_websub_notification_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_WEBSUB_NOTIFICATION_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_WEBSUB_NOTIFICATION_PATH.exists())

    async def test_handles_atom_notification_and_collects_subscription_results(self):
        subscriptions = [
            _subscription(id=1, guild_id=10),
            _subscription(id=2, guild_id=20),
        ]
        find_calls: list[str] = []
        processed: list[tuple[int, str]] = []

        async def find_subscriptions(channel_id):
            find_calls.append(channel_id)
            return subscriptions if channel_id == "UC_MATCHED" else []

        async def process_video_candidate(subscription, video_id):
            processed.append((subscription.id, video_id))
            return f"status-{subscription.id}"

        result = await handle_youtube_websub_notification(
            SAMPLE_ATOM,
            find_subscriptions=find_subscriptions,
            process_video_candidate=process_video_candidate,
        )

        self.assertEqual(find_calls, ["UC_MATCHED", "UC_IGNORED"])
        self.assertEqual(processed, [(1, "VIDEO123"), (2, "VIDEO123")])
        self.assertEqual(result["received"], 2)
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["ignored"], 1)
        self.assertEqual(
            result["results"],
            [
                {
                    "guild_id": 10,
                    "subscription_id": 1,
                    "video_id": "VIDEO123",
                    "status": "status-1",
                },
                {
                    "guild_id": 20,
                    "subscription_id": 2,
                    "video_id": "VIDEO123",
                    "status": "status-2",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
