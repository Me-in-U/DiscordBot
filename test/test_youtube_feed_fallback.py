import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from util.youtube.feed_fallback import (
    YouTubeFeedFallbackState,
    fetch_youtube_feed_entries,
    poll_youtube_feed_fallback,
    remember_youtube_feed_entry_seen,
    should_poll_youtube_feed,
)
from util.youtube.subscriptions import YouTubeSubscription
from util.youtube.websub import YouTubeAtomEntry


YOUTUBE_FEED_FALLBACK_PATH = Path("util/youtube/feed_fallback.py")
LEGACY_YOUTUBE_FEED_FALLBACK_PATH = Path("util/youtube_feed_fallback.py")


def _subscription(**overrides) -> YouTubeSubscription:
    data = {
        "id": 1,
        "guild_id": 10,
        "channel_name": "채널",
        "channel_id": "UC_TEST",
        "channel_handle": None,
        "source_input": "UC_TEST",
        "websub_subscribed_at": None,
        "websub_lease_seconds": None,
        "pending_videos": {},
        "notified_video_ids": [],
        "live_alert_enabled": True,
        "upload_alert_enabled": True,
        "upload_alert_enabled_at": None,
        "notified_upload_video_ids": [],
        "community_alert_enabled": False,
        "notified_community_post_ids": [],
    }
    data.update(overrides)
    return YouTubeSubscription(**data)


def _entry(
    video_id: str,
    *,
    channel_id: str = "UC_TEST",
    updated: str = "2026-06-23T01:10:00+00:00",
) -> YouTubeAtomEntry:
    return YouTubeAtomEntry(
        video_id=video_id,
        channel_id=channel_id,
        title="영상",
        link=f"https://www.youtube.com/watch?v={video_id}",
        published="2026-06-23T01:00:00+00:00",
        updated=updated,
    )


class YouTubeFeedFallbackTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_feed_fallback_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_FEED_FALLBACK_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_FEED_FALLBACK_PATH.exists())

    def test_should_poll_records_timestamp_and_throttles_recent_checks(self):
        state = YouTubeFeedFallbackState()
        first_check = datetime(2026, 6, 23, 1, 10, tzinfo=timezone.utc)
        recent_check = datetime(2026, 6, 23, 1, 12, tzinfo=timezone.utc)
        later_check = datetime(2026, 6, 23, 1, 16, tzinfo=timezone.utc)

        self.assertTrue(
            should_poll_youtube_feed(
                state,
                1,
                now=first_check,
                interval_seconds=300,
            )
        )
        self.assertFalse(
            should_poll_youtube_feed(
                state,
                1,
                now=recent_check,
                interval_seconds=300,
            )
        )
        self.assertTrue(
            should_poll_youtube_feed(
                state,
                1,
                now=later_check,
                interval_seconds=300,
            )
        )

    def test_remember_feed_entry_seen_trims_oldest_entries(self):
        state = YouTubeFeedFallbackState(
            seen_updates={1: {f"old-{index}": "u" for index in range(50)}}
        )

        remember_youtube_feed_entry_seen(
            state,
            1,
            "new-video",
            "2026-06-23T01:10:00+00:00",
            limit=50,
        )

        self.assertNotIn("old-0", state.seen_updates[1])
        self.assertEqual(
            state.seen_updates[1]["new-video"],
            "2026-06-23T01:10:00+00:00",
        )
        self.assertEqual(len(state.seen_updates[1]), 50)

    async def test_fetch_feed_entries_parses_atom_and_returns_empty_on_http_error(self):
        success_entries = await fetch_youtube_feed_entries(
            _Session(
                200,
                """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>VIDEO123</yt:videoId>
    <yt:channelId>UC_TEST</yt:channelId>
    <title>테스트 라이브</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=VIDEO123"/>
    <published>2026-06-23T01:00:00+00:00</published>
    <updated>2026-06-23T01:10:00+00:00</updated>
  </entry>
</feed>
""",
            ),
            _subscription(),
            log=lambda _message: None,
        )
        failed_entries = await fetch_youtube_feed_entries(
            _Session(500, "server error"),
            _subscription(),
            log=lambda _message: None,
        )

        self.assertEqual([entry.video_id for entry in success_entries], ["VIDEO123"])
        self.assertEqual(failed_entries, [])

    async def test_poll_feed_fallback_processes_matching_entries_and_refreshes(self):
        state = YouTubeFeedFallbackState(
            seen_updates={
                1: {"skip-seen": "2026-06-23T01:10:00+00:00"},
            }
        )
        subscription = _subscription(
            pending_videos={},
            notified_video_ids=[],
            notified_upload_video_ids=[],
        )
        processed_video_ids: list[str] = []

        async def process_candidate(_subscription, video_id: str):
            processed_video_ids.append(video_id)
            return "processed"

        async def fetch_entries(_session, _subscription):
            return [
                _entry("wrong-channel", channel_id="UC_OTHER"),
                _entry("skip-seen"),
                _entry("process-me", updated="2026-06-23T01:11:00+00:00"),
            ]

        async def get_subscription(subscription_id: int):
            return replace(subscription, channel_name=f"refreshed-{subscription_id}")

        result = await poll_youtube_feed_fallback(
            process_candidate,
            state,
            subscription,
            object(),
            fetch_entries=fetch_entries,
            get_subscription=get_subscription,
            now=datetime(2026, 6, 23, 1, 10, tzinfo=timezone.utc),
            interval_seconds=300,
            max_entries=5,
        )

        self.assertEqual(processed_video_ids, ["process-me"])
        self.assertEqual(result.channel_name, "refreshed-1")
        self.assertEqual(
            state.seen_updates[1]["process-me"],
            "2026-06-23T01:11:00+00:00",
        )


class _Session:
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body

    def get(self, _url: str):
        return _Response(self.status, self.body)


class _Response:
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return self.body


if __name__ == "__main__":
    unittest.main()
