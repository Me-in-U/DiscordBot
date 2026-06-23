import unittest

import aiohttp

from util.youtube_community import YouTubeCommunityPost
from util.youtube_community_polling import poll_youtube_community_posts
from util.youtube_subscriptions import YouTubeSubscription


def _subscription(**overrides) -> YouTubeSubscription:
    data = {
        "id": 1,
        "guild_id": 10,
        "channel_name": "커뮤니티 채널",
        "channel_id": "UC_TEST",
        "channel_handle": None,
        "source_input": "UC_TEST",
        "websub_subscribed_at": None,
        "websub_lease_seconds": None,
        "pending_videos": {},
        "notified_video_ids": [],
        "live_alert_enabled": False,
        "upload_alert_enabled": False,
        "upload_alert_enabled_at": None,
        "notified_upload_video_ids": [],
        "community_alert_enabled": True,
        "notified_community_post_ids": [],
    }
    data.update(overrides)
    return YouTubeSubscription(**data)


class YouTubeCommunityPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_subscription_skips_fetch_and_processing(self):
        subscription = _subscription(community_alert_enabled=False)

        async def fetch_posts(*_args, **_kwargs):
            raise AssertionError("disabled subscription should not fetch posts")

        async def process_notifications(*_args, **_kwargs):
            raise AssertionError("disabled subscription should not process posts")

        result = await poll_youtube_community_posts(
            object(),
            subscription,
            fetch_posts=fetch_posts,
            process_notifications=process_notifications,
        )

        self.assertIs(result, subscription)

    async def test_enabled_subscription_fetches_posts_and_processes_notifications(self):
        subscription = _subscription()
        updated_subscription = _subscription(notified_community_post_ids=["post-1"])
        posts = [
            YouTubeCommunityPost(
                post_id="post-1",
                url="https://youtube.com/post/post-1",
            )
        ]
        fetched: list[tuple[str, int]] = []
        processed: list[tuple[YouTubeSubscription, list[YouTubeCommunityPost]]] = []

        async def fetch_posts(channel_id, *, limit):
            fetched.append((channel_id, limit))
            return posts

        async def process_notifications(bot, target_subscription, target_posts):
            processed.append((target_subscription, list(target_posts)))
            return updated_subscription

        result = await poll_youtube_community_posts(
            object(),
            subscription,
            fetch_posts=fetch_posts,
            process_notifications=process_notifications,
        )

        self.assertIs(result, updated_subscription)
        self.assertEqual(fetched, [("UC_TEST", 10)])
        self.assertEqual(processed, [(subscription, posts)])

    async def test_fetch_failure_logs_warning_and_returns_original_subscription(self):
        subscription = _subscription()
        warnings: list[tuple[str, tuple, dict]] = []

        async def fetch_posts(_channel_id, *, limit):
            raise aiohttp.ClientError("network failed")

        async def process_notifications(*_args, **_kwargs):
            raise AssertionError("failed fetch should not process posts")

        result = await poll_youtube_community_posts(
            object(),
            subscription,
            fetch_posts=fetch_posts,
            process_notifications=process_notifications,
            log_warning=lambda message, *args, **kwargs: warnings.append(
                (message, args, kwargs)
            ),
        )

        self.assertIs(result, subscription)
        self.assertEqual(len(warnings), 1)
        self.assertIn("YouTube 커뮤니티 게시물 조회 실패", warnings[0][0])
        self.assertEqual(warnings[0][1], ("UC_TEST",))
        self.assertTrue(warnings[0][2]["exc_info"])


if __name__ == "__main__":
    unittest.main()
