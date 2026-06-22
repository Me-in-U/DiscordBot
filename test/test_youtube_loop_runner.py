import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from util.youtube.loop_runner import (
    run_youtube_community_posts,
    run_youtube_notification_candidates,
)
from util.youtube_subscriptions import YouTubeSubscription


YOUTUBE_LOOP_RUNNER_PATH = Path("util/youtube/loop_runner.py")
LEGACY_YOUTUBE_LOOP_RUNNER_PATH = Path("util/youtube_loop_runner.py")


def _subscription(
    subscription_id: int,
    *,
    pending_videos: dict | None = None,
    community_alert_enabled: bool = False,
) -> YouTubeSubscription:
    return YouTubeSubscription(
        id=subscription_id,
        guild_id=10,
        channel_name=f"채널 {subscription_id}",
        channel_id=f"UC_{subscription_id}",
        channel_handle=None,
        source_input=f"UC_{subscription_id}",
        websub_subscribed_at=None,
        websub_lease_seconds=None,
        pending_videos=pending_videos or {},
        notified_video_ids=[],
        community_alert_enabled=community_alert_enabled,
    )


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSessionFactory:
    def __init__(self, **_kwargs):
        self.session = FakeSession()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeNotificationOwner:
    def __init__(self):
        self.deleted_legacy_setting = False
        self.removed_pending: list[str] = []
        self.processed_candidates: list[str] = []
        self.processed_pending: list[dict] = []

    async def _delete_legacy_youtube_live_checker_setting_once(self):
        self.deleted_legacy_setting = True

    async def _poll_youtube_feed_fallback(self, subscription, _session):
        return subscription

    async def _remove_pending_youtube_video(self, subscription, video_id):
        self.removed_pending.append(video_id)
        pending = dict(subscription.pending_videos)
        pending.pop(video_id, None)
        return replace(subscription, pending_videos=pending)

    def _should_check_pending_youtube_video(self, pending_entry):
        return bool(pending_entry.get("check"))

    async def _process_youtube_video_candidate(self, subscription, video_id):
        self.processed_candidates.append(video_id)
        self.processed_pending.append(dict(subscription.pending_videos))


class FakeCommunityOwner:
    def __init__(self):
        self.polled_subscription_ids: list[int] = []

    async def _poll_youtube_community_posts(self, subscription):
        self.polled_subscription_ids.append(subscription.id)


class YouTubeLoopRunnerTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_loop_runner_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_LOOP_RUNNER_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_LOOP_RUNNER_PATH.exists())

    async def test_notification_runner_processes_pending_candidates(self):
        owner = FakeNotificationOwner()
        subscription = _subscription(
            1,
            pending_videos={
                "bad": "not-a-dict",
                "skip": {"check": False},
                "ready": {"check": True},
            },
        )

        async def _touch_pending(subscription, video_id, pending_entry):
            pending = dict(subscription.pending_videos)
            pending[str(video_id)] = {
                **pending_entry,
                "lastCheckedAt": "2026-06-23T01:10:00+00:00",
            }
            return replace(subscription, pending_videos=pending)

        touch_pending = AsyncMock(side_effect=_touch_pending)

        with patch(
            "util.youtube.loop_runner.list_all_youtube_subscriptions",
            new=AsyncMock(return_value=[subscription]),
        ):
            with patch(
                "util.youtube.loop_runner.touch_pending_youtube_video_check",
                touch_pending,
            ):
                with patch(
                    "util.youtube.loop_runner.get_youtube_subscription",
                    new=AsyncMock(return_value=None),
                ):
                    with patch(
                        "util.youtube.loop_runner.aiohttp.ClientSession",
                        FakeSessionFactory,
                    ):
                        await run_youtube_notification_candidates(owner)

        self.assertTrue(owner.deleted_legacy_setting)
        self.assertEqual(owner.removed_pending, ["bad"])
        self.assertEqual(owner.processed_candidates, ["ready"])
        touch_pending.assert_awaited_once()
        self.assertEqual(touch_pending.await_args.args[1], "ready")
        self.assertEqual(
            owner.processed_pending,
            [
                {
                    "skip": {"check": False},
                    "ready": {
                        "check": True,
                        "lastCheckedAt": "2026-06-23T01:10:00+00:00",
                    },
                }
            ],
        )

    async def test_community_runner_polls_only_enabled_subscriptions(self):
        owner = FakeCommunityOwner()
        subscriptions = [
            _subscription(1, community_alert_enabled=False),
            _subscription(2, community_alert_enabled=True),
        ]

        with patch(
            "util.youtube.loop_runner.list_all_youtube_subscriptions",
            new=AsyncMock(return_value=subscriptions),
        ):
            await run_youtube_community_posts(owner)

        self.assertEqual(owner.polled_subscription_ids, [2])


if __name__ == "__main__":
    unittest.main()
