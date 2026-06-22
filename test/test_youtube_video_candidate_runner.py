import unittest
from pathlib import Path

from util.youtube.video_candidate_runner import process_youtube_video_candidate
from util.youtube_subscriptions import YouTubeSubscription
from util.youtube_websub import YouTubeVideoLiveStatus, YouTubeVideoStatus


YOUTUBE_VIDEO_CANDIDATE_RUNNER_PATH = Path(
    "util/youtube/video_candidate_runner.py"
)
LEGACY_YOUTUBE_VIDEO_CANDIDATE_RUNNER_PATH = Path(
    "util/youtube_video_candidate_runner.py"
)


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
        "upload_alert_enabled": False,
        "upload_alert_enabled_at": None,
        "notified_upload_video_ids": [],
        "community_alert_enabled": False,
        "notified_community_post_ids": [],
    }
    data.update(overrides)
    return YouTubeSubscription(**data)


def _status(video_id: str, status: YouTubeVideoStatus, **overrides):
    data = {
        "video_id": video_id,
        "channel_id": "UC_TEST",
        "title": "영상",
        "status": status,
        "published_at": None,
        "scheduled_start_time": None,
    }
    data.update(overrides)
    return YouTubeVideoLiveStatus(**data)


class YouTubeVideoCandidateRunnerTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_video_candidate_runner_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_VIDEO_CANDIDATE_RUNNER_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_VIDEO_CANDIDATE_RUNNER_PATH.exists())

    async def test_live_candidate_sends_and_marks_notification(self):
        owner = _Owner(_status("live-1", YouTubeVideoStatus.LIVE))
        subscription = _subscription()

        outcome = await process_youtube_video_candidate(
            owner,
            subscription,
            "live-1",
        )

        self.assertEqual(outcome, "notified")
        self.assertEqual(owner.fetched_video_ids, ["live-1"])
        self.assertEqual(owner.sent_live_ids, ["live-1"])
        self.assertEqual(owner.marked_live_ids, ["live-1"])
        self.assertEqual(owner.removed_pending_ids, [])

    async def test_upload_candidate_respects_disabled_upload_alert(self):
        owner = _Owner(_status("upload-1", YouTubeVideoStatus.UPLOAD))
        subscription = _subscription(upload_alert_enabled=False)

        outcome = await process_youtube_video_candidate(
            owner,
            subscription,
            "upload-1",
        )

        self.assertEqual(outcome, "upload_disabled")
        self.assertEqual(owner.removed_pending_ids, ["upload-1"])
        self.assertEqual(owner.sent_upload_ids, [])
        self.assertEqual(owner.marked_upload_ids, [])

    async def test_channel_mismatch_removes_pending_candidate(self):
        owner = _Owner(
            _status(
                "wrong-channel",
                YouTubeVideoStatus.LIVE,
                channel_id="UC_OTHER",
            )
        )
        subscription = _subscription(channel_id="UC_TEST")

        outcome = await process_youtube_video_candidate(
            owner,
            subscription,
            "wrong-channel",
        )

        self.assertEqual(outcome, "channel_mismatch")
        self.assertEqual(owner.removed_pending_ids, ["wrong-channel"])
        self.assertEqual(owner.sent_live_ids, [])


class _Owner:
    def __init__(self, status):
        self.status = status
        self.fetched_video_ids: list[str] = []
        self.removed_pending_ids: list[str] = []
        self.sent_live_ids: list[str] = []
        self.sent_upload_ids: list[str] = []
        self.marked_live_ids: list[str] = []
        self.marked_upload_ids: list[str] = []
        self.remembered_pending_ids: list[str] = []

    async def _fetch_youtube_video_status(self, video_id: str):
        self.fetched_video_ids.append(video_id)
        return self.status

    async def _remove_pending_youtube_video(self, subscription, video_id: str):
        self.removed_pending_ids.append(video_id)
        return subscription

    def _get_notified_video_ids(self, subscription):
        return set(subscription.notified_video_ids)

    def _get_notified_upload_video_ids(self, subscription):
        return set(subscription.notified_upload_video_ids)

    async def _send_youtube_live_notification(self, _subscription, status):
        self.sent_live_ids.append(status.video_id)
        return True

    async def _send_youtube_upload_notification(self, _subscription, status):
        self.sent_upload_ids.append(status.video_id)
        return True

    async def _mark_youtube_video_notified(self, subscription, video_id: str):
        self.marked_live_ids.append(video_id)
        return subscription

    async def _mark_youtube_upload_video_notified(self, subscription, video_id: str):
        self.marked_upload_ids.append(video_id)
        return subscription

    async def _remember_pending_youtube_video(self, subscription, status):
        self.remembered_pending_ids.append(status.video_id)
        return subscription


if __name__ == "__main__":
    unittest.main()
