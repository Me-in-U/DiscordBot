import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from util.youtube.notification_state import (
    mark_youtube_upload_video_notified,
    mark_youtube_video_notified,
    notified_id_set,
    parse_youtube_datetime,
    remember_pending_youtube_video,
    remove_pending_youtube_video,
    should_check_pending_youtube_video,
    touch_pending_youtube_video_check,
)
from util.youtube_subscriptions import YouTubeSubscription
from util.youtube_websub import YouTubeVideoLiveStatus, YouTubeVideoStatus


YOUTUBE_NOTIFICATION_STATE_PATH = Path("util/youtube/notification_state.py")
LEGACY_YOUTUBE_NOTIFICATION_STATE_PATH = Path("util/youtube_notification_state.py")


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


def _status(video_id: str = "live-1") -> YouTubeVideoLiveStatus:
    return YouTubeVideoLiveStatus(
        video_id=video_id,
        channel_id="UC_TEST",
        title="라이브 제목",
        status=YouTubeVideoStatus.UPCOMING,
        published_at=None,
        scheduled_start_time="2026-06-23T01:20:00Z",
    )


class _Recorder:
    def __init__(self):
        self.calls: list[tuple[int, dict]] = []

    async def update_subscription_state(self, subscription_id: int, **kwargs) -> None:
        self.calls.append((subscription_id, kwargs))

    async def update_upload_state(self, subscription_id: int, **kwargs) -> None:
        self.calls.append((subscription_id, kwargs))


class YouTubeNotificationStateTests(unittest.TestCase):
    def test_youtube_notification_state_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_NOTIFICATION_STATE_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_NOTIFICATION_STATE_PATH.exists())

    def test_notified_id_set_normalizes_truthy_values_to_strings(self):
        self.assertEqual(
            notified_id_set(["VIDEO1", 2, None, "", "VIDEO1"]),
            {"VIDEO1", "2"},
        )

    def test_parse_youtube_datetime_accepts_zulu_and_naive_values(self):
        self.assertEqual(
            parse_youtube_datetime("2026-06-23T01:02:03Z"),
            datetime(2026, 6, 23, 1, 2, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_youtube_datetime("2026-06-23T01:02:03"),
            datetime(2026, 6, 23, 1, 2, 3, tzinfo=timezone.utc),
        )
        self.assertIsNone(parse_youtube_datetime("not-a-date"))

    def test_should_check_pending_video_respects_recent_last_check(self):
        now = datetime(2026, 6, 23, 1, 10, tzinfo=timezone.utc)

        self.assertFalse(
            should_check_pending_youtube_video(
                {"lastCheckedAt": "2026-06-23T01:07:00Z"},
                now=now,
                check_interval_seconds=300,
            )
        )

    def test_should_check_pending_video_uses_scheduled_window(self):
        now = datetime(2026, 6, 23, 1, 10, tzinfo=timezone.utc)

        self.assertTrue(
            should_check_pending_youtube_video(
                {
                    "lastCheckedAt": "2026-06-23T01:00:00Z",
                    "scheduledStartTime": "2026-06-23T01:20:00Z",
                },
                now=now,
                early_window=timedelta(minutes=15),
                expire_window=timedelta(hours=24),
            )
        )
        self.assertFalse(
            should_check_pending_youtube_video(
                {
                    "lastCheckedAt": "2026-06-23T01:00:00Z",
                    "scheduledStartTime": "2026-06-23T02:00:00Z",
                },
                now=now,
                early_window=timedelta(minutes=15),
                expire_window=timedelta(hours=24),
            )
        )


class YouTubeNotificationStatePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_mark_live_notification_trims_ids_and_removes_pending_video(self):
        recorder = _Recorder()
        subscription = _subscription(
            pending_videos={"live-new": {"title": "이전"}},
            notified_video_ids=[f"old-{index}" for index in range(30)],
        )

        updated = await mark_youtube_video_notified(
            subscription,
            "live-new",
            update_state=recorder.update_subscription_state,
        )

        self.assertNotIn("live-new", updated.pending_videos)
        self.assertEqual(updated.notified_video_ids[-1], "live-new")
        self.assertEqual(len(updated.notified_video_ids), 30)
        self.assertNotIn("old-0", updated.notified_video_ids)
        self.assertEqual(
            recorder.calls,
            [
                (
                    1,
                    {
                        "pending_videos": {},
                        "notified_video_ids": updated.notified_video_ids,
                    },
                )
            ],
        )

    async def test_mark_upload_notification_updates_upload_notified_ids(self):
        recorder = _Recorder()
        subscription = _subscription(notified_upload_video_ids=["upload-old"])

        updated = await mark_youtube_upload_video_notified(
            subscription,
            "upload-new",
            update_upload_state=recorder.update_upload_state,
        )

        self.assertEqual(
            updated.notified_upload_video_ids,
            ["upload-old", "upload-new"],
        )
        self.assertEqual(
            recorder.calls,
            [
                (
                    1,
                    {"notified_upload_video_ids": ["upload-old", "upload-new"]},
                )
            ],
        )

    async def test_remember_pending_video_records_status_and_checked_at(self):
        recorder = _Recorder()
        checked_at = datetime(2026, 6, 23, 1, 10, tzinfo=timezone.utc)
        subscription = _subscription()

        updated = await remember_pending_youtube_video(
            subscription,
            _status("upcoming-1"),
            now=checked_at,
            update_state=recorder.update_subscription_state,
        )

        self.assertEqual(
            updated.pending_videos["upcoming-1"],
            {
                "title": "라이브 제목",
                "channelId": "UC_TEST",
                "scheduledStartTime": "2026-06-23T01:20:00Z",
                "lastCheckedAt": "2026-06-23T01:10:00+00:00",
            },
        )
        self.assertEqual(recorder.calls[0][0], 1)
        self.assertEqual(
            recorder.calls[0][1]["pending_videos"],
            updated.pending_videos,
        )

    async def test_remove_pending_video_persists_remaining_pending_state(self):
        recorder = _Recorder()
        subscription = _subscription(
            pending_videos={
                "remove-me": {"title": "삭제"},
                "keep-me": {"title": "유지"},
            },
            notified_video_ids=["live-1"],
        )

        updated = await remove_pending_youtube_video(
            subscription,
            "remove-me",
            update_state=recorder.update_subscription_state,
        )

        self.assertEqual(updated.pending_videos, {"keep-me": {"title": "유지"}})
        self.assertEqual(
            recorder.calls,
            [
                (
                    1,
                    {
                        "pending_videos": {"keep-me": {"title": "유지"}},
                        "notified_video_ids": ["live-1"],
                    },
                )
            ],
        )

    async def test_touch_pending_video_check_persists_last_checked_at(self):
        recorder = _Recorder()
        checked_at = datetime(2026, 6, 23, 1, 10, tzinfo=timezone.utc)
        subscription = _subscription(
            pending_videos={"pending-1": {"title": "기존"}},
            notified_video_ids=["live-1"],
        )

        updated = await touch_pending_youtube_video_check(
            subscription,
            "pending-1",
            {"title": "기존"},
            now=checked_at,
            update_state=recorder.update_subscription_state,
        )

        self.assertEqual(
            updated.pending_videos["pending-1"]["lastCheckedAt"],
            "2026-06-23T01:10:00+00:00",
        )
        self.assertEqual(
            recorder.calls,
            [
                (
                    1,
                    {
                        "pending_videos": updated.pending_videos,
                        "notified_video_ids": ["live-1"],
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
