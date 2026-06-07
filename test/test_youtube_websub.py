import unittest
from pathlib import Path

import util.youtube_websub as youtube_websub

from util.youtube_websub import (
    YouTubeVideoStatus,
    build_youtube_upload_notification_message,
    build_youtube_feed_topic_url,
    classify_video_item,
    parse_youtube_atom_entries,
    should_send_youtube_upload_alert,
    should_process_youtube_feed_update,
)


SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <link rel="hub" href="https://pubsubhubbub.appspot.com"/>
  <link rel="self" href="https://www.youtube.com/xml/feeds/videos.xml?channel_id=UC_TEST"/>
  <title>YouTube video feed</title>
  <entry>
    <id>yt:video:VIDEO123</id>
    <yt:videoId>VIDEO123</yt:videoId>
    <yt:channelId>UC_TEST</yt:channelId>
    <title>테스트 라이브</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=VIDEO123"/>
    <author>
      <name>테스트 채널</name>
    </author>
    <published>2026-05-06T10:00:00+00:00</published>
    <updated>2026-05-06T10:01:00+00:00</updated>
  </entry>
</feed>
"""

LOOP_PATH = Path("cogs/loop.py")


class YouTubeWebSubTests(unittest.TestCase):
    def test_parses_youtube_atom_entry(self):
        entries = parse_youtube_atom_entries(SAMPLE_ATOM)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].video_id, "VIDEO123")
        self.assertEqual(entries[0].channel_id, "UC_TEST")
        self.assertEqual(entries[0].title, "테스트 라이브")
        self.assertEqual(entries[0].link, "https://www.youtube.com/watch?v=VIDEO123")

    def test_builds_channel_feed_topic_url(self):
        self.assertEqual(
            build_youtube_feed_topic_url("UC_TEST"),
            "https://www.youtube.com/feeds/videos.xml?channel_id=UC_TEST",
        )

    def test_builds_live_notification_message_as_masked_link_header(self):
        build_message = getattr(
            youtube_websub,
            "build_youtube_live_notification_message",
            None,
        )
        self.assertIsNotNone(build_message)
        self.assertEqual(
            build_message("VIDEO123"),
            "## 🔴 [LIVE 시작](https://youtu.be/VIDEO123)",
        )

    def test_builds_upload_notification_message_with_channel_and_title(self):
        self.assertEqual(
            build_youtube_upload_notification_message(
                "테스트 채널",
                "새 영상 제목",
                "VIDEO123",
            ),
            "## 📺 테스트 채널 새 영상\n**새 영상 제목**\nhttps://youtu.be/VIDEO123",
        )

    def test_classifies_current_live_video(self):
        status = classify_video_item(
            {
                "id": "VIDEO123",
                "snippet": {
                    "title": "라이브 중",
                    "channelId": "UC_TEST",
                    "liveBroadcastContent": "live",
                },
                "liveStreamingDetails": {
                    "actualStartTime": "2026-05-06T10:00:00Z",
                },
            }
        )

        self.assertEqual(status.status, YouTubeVideoStatus.LIVE)
        self.assertEqual(status.video_id, "VIDEO123")
        self.assertEqual(status.scheduled_start_time, None)

    def test_classifies_upcoming_live_video(self):
        status = classify_video_item(
            {
                "id": "VIDEO123",
                "snippet": {
                    "title": "예정 방송",
                    "channelId": "UC_TEST",
                    "liveBroadcastContent": "upcoming",
                },
                "liveStreamingDetails": {
                    "scheduledStartTime": "2026-05-06T12:00:00Z",
                },
            }
        )

        self.assertEqual(status.status, YouTubeVideoStatus.UPCOMING)
        self.assertEqual(status.scheduled_start_time, "2026-05-06T12:00:00Z")

    def test_classifies_completed_live_as_not_live(self):
        status = classify_video_item(
            {
                "id": "VIDEO123",
                "snippet": {
                    "title": "종료 방송",
                    "channelId": "UC_TEST",
                    "liveBroadcastContent": "none",
                },
                "liveStreamingDetails": {
                    "actualStartTime": "2026-05-06T10:00:00Z",
                    "actualEndTime": "2026-05-06T11:00:00Z",
                },
            }
        )

        self.assertEqual(status.status, YouTubeVideoStatus.NOT_LIVE)

    def test_classifies_regular_upload_separately_from_finished_live(self):
        status = classify_video_item(
            {
                "id": "UPLOAD123",
                "snippet": {
                    "title": "일반 업로드",
                    "channelId": "UC_TEST",
                    "publishedAt": "2026-05-18T10:00:00Z",
                    "liveBroadcastContent": "none",
                },
            }
        )

        self.assertEqual(status.status, YouTubeVideoStatus.UPLOAD)
        self.assertEqual(status.published_at, "2026-05-18T10:00:00Z")

    def test_classifies_short_upload_candidate_separately_from_uploads(self):
        shorts_status = getattr(YouTubeVideoStatus, "SHORTS", None)
        self.assertIsNotNone(shorts_status)

        status = classify_video_item(
            {
                "id": "SHORT123",
                "snippet": {
                    "title": "짧은 업로드",
                    "channelId": "UC_TEST",
                    "publishedAt": "2026-05-18T10:00:00Z",
                    "liveBroadcastContent": "none",
                },
                "contentDetails": {
                    "duration": "PT2M59S",
                },
            }
        )

        self.assertEqual(status.status, shorts_status)

    def test_classifies_upload_over_three_minutes_as_regular_upload(self):
        status = classify_video_item(
            {
                "id": "UPLOAD123",
                "snippet": {
                    "title": "3분 초과 업로드",
                    "channelId": "UC_TEST",
                    "publishedAt": "2026-05-18T10:00:00Z",
                    "liveBroadcastContent": "none",
                },
                "contentDetails": {
                    "duration": "PT3M1S",
                },
            }
        )

        self.assertEqual(status.status, YouTubeVideoStatus.UPLOAD)

    def test_loop_fetches_content_details_and_skips_shorts(self):
        source = LOOP_PATH.read_text(encoding="utf-8")

        self.assertIn("snippet,liveStreamingDetails,status,contentDetails", source)
        self.assertIn("shorts_skipped", source)

    def test_loop_defines_ten_minute_community_post_check(self):
        source = LOOP_PATH.read_text(encoding="utf-8")

        self.assertIn("@tasks.loop(minutes=10)", source)
        self.assertIn("youtube_community_check", source)
        self.assertIn("community_alert_enabled", source)
        self.assertIn("update_youtube_community_notification_state", source)

    def test_upload_alert_respects_enabled_at_cutoff(self):
        self.assertFalse(
            should_send_youtube_upload_alert(
                upload_alert_enabled=True,
                upload_alert_enabled_at="2026-05-18T10:00:00+00:00",
                published_at="2026-05-18T09:59:59Z",
            )
        )
        self.assertTrue(
            should_send_youtube_upload_alert(
                upload_alert_enabled=True,
                upload_alert_enabled_at="2026-05-18T10:00:00+00:00",
                published_at="2026-05-18T10:00:00Z",
            )
        )

    def test_upload_alert_disabled_blocks_regular_upload(self):
        self.assertFalse(
            should_send_youtube_upload_alert(
                upload_alert_enabled=False,
                upload_alert_enabled_at=None,
                published_at="2026-05-18T10:00:00Z",
            )
        )

    def test_processes_unseen_feed_update(self):
        self.assertTrue(
            should_process_youtube_feed_update(
                video_id="VIDEO123",
                entry_updated="2026-05-07T07:03:59+00:00",
                seen_updates={},
                pending_videos={},
                notified_video_ids=[],
            )
        )

    def test_skips_unchanged_feed_update(self):
        self.assertFalse(
            should_process_youtube_feed_update(
                video_id="VIDEO123",
                entry_updated="2026-05-07T07:03:59+00:00",
                seen_updates={"VIDEO123": "2026-05-07T07:03:59+00:00"},
                pending_videos={},
                notified_video_ids=[],
            )
        )

    def test_processes_pending_feed_update_even_when_unchanged(self):
        self.assertTrue(
            should_process_youtube_feed_update(
                video_id="VIDEO123",
                entry_updated="2026-05-07T07:03:59+00:00",
                seen_updates={"VIDEO123": "2026-05-07T07:03:59+00:00"},
                pending_videos={"VIDEO123": {"scheduledStartTime": None}},
                notified_video_ids=[],
            )
        )

    def test_skips_notified_feed_update(self):
        self.assertFalse(
            should_process_youtube_feed_update(
                video_id="VIDEO123",
                entry_updated="2026-05-07T07:03:59+00:00",
                seen_updates={},
                pending_videos={"VIDEO123": {"scheduledStartTime": None}},
                notified_video_ids=["VIDEO123"],
            )
        )

    def test_skips_notified_upload_feed_update(self):
        self.assertFalse(
            should_process_youtube_feed_update(
                video_id="VIDEO123",
                entry_updated="2026-05-07T07:03:59+00:00",
                seen_updates={},
                pending_videos={},
                notified_video_ids=[],
                notified_upload_video_ids=["VIDEO123"],
            )
        )


if __name__ == "__main__":
    unittest.main()
