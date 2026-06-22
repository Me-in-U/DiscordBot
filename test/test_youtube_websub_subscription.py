import unittest
from datetime import datetime, timezone
from pathlib import Path

from util.youtube.websub_subscription import (
    DEFAULT_WEBSUB_LEASE_SECONDS,
    build_configured_youtube_websub_callback_url,
    ensure_youtube_websub_subscription,
    request_youtube_websub_subscription,
    unsubscribe_youtube_websub_subscription,
)
from util.youtube_subscriptions import YouTubeSubscription


YOUTUBE_WEBSUB_SUBSCRIPTION_PATH = Path("util/youtube/websub_subscription.py")
LEGACY_YOUTUBE_WEBSUB_SUBSCRIPTION_PATH = Path("util/youtube_websub_subscription.py")


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


class YouTubeWebSubSubscriptionTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_websub_subscription_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_WEBSUB_SUBSCRIPTION_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_WEBSUB_SUBSCRIPTION_PATH.exists())

    def test_build_configured_callback_url_handles_missing_values_and_token(self):
        self.assertEqual(build_configured_youtube_websub_callback_url("", "token"), "")
        self.assertEqual(
            build_configured_youtube_websub_callback_url(
                "https://bot.example/youtube/websub",
                "",
            ),
            "https://bot.example/youtube/websub",
        )
        self.assertEqual(
            build_configured_youtube_websub_callback_url(
                "https://bot.example/youtube/websub?existing=1",
                "token",
            ),
            "https://bot.example/youtube/websub?existing=1&token=token",
        )

    async def test_ensure_websub_subscribes_only_live_or_upload_subscriptions(self):
        live_subscription = _subscription(id=1, channel_id="UC_LIVE")
        upload_subscription = _subscription(
            id=2,
            channel_id="UC_UPLOAD",
            live_alert_enabled=False,
            upload_alert_enabled=True,
        )
        community_only_subscription = _subscription(
            id=3,
            channel_id="UC_COMMUNITY",
            live_alert_enabled=False,
            upload_alert_enabled=False,
            community_alert_enabled=True,
        )
        requested: list[tuple[int, str]] = []
        updated: list[tuple[int, datetime, int]] = []
        now = datetime(2026, 6, 23, 1, 10, tzinfo=timezone.utc)

        async def list_subscriptions():
            return [
                live_subscription,
                upload_subscription,
                community_only_subscription,
            ]

        async def request_subscription(subscription, *, callback_url, mode):
            requested.append((subscription.id, mode))
            return True

        async def update_websub_state(
            subscription_id,
            *,
            websub_subscribed_at,
            websub_lease_seconds,
        ):
            updated.append(
                (subscription_id, websub_subscribed_at, websub_lease_seconds)
            )

        subscribed = await ensure_youtube_websub_subscription(
            callback_url="https://bot.example/youtube/websub?token=token",
            list_subscriptions=list_subscriptions,
            request_subscription=request_subscription,
            update_websub_state=update_websub_state,
            now=now,
        )

        self.assertTrue(subscribed)
        self.assertEqual(requested, [(1, "subscribe"), (2, "subscribe")])
        self.assertEqual(
            updated,
            [
                (1, now, DEFAULT_WEBSUB_LEASE_SECONDS),
                (2, now, DEFAULT_WEBSUB_LEASE_SECONDS),
            ],
        )

    async def test_ensure_websub_returns_false_when_any_request_fails(self):
        updated: list[int] = []

        async def list_subscriptions():
            return [
                _subscription(id=1, channel_id="UC_OK"),
                _subscription(id=2, channel_id="UC_FAIL"),
            ]

        async def request_subscription(subscription, *, callback_url, mode):
            return subscription.channel_id != "UC_FAIL"

        async def update_websub_state(subscription_id, **_kwargs):
            updated.append(subscription_id)

        subscribed = await ensure_youtube_websub_subscription(
            callback_url="https://bot.example/youtube/websub?token=token",
            list_subscriptions=list_subscriptions,
            request_subscription=request_subscription,
            update_websub_state=update_websub_state,
        )

        self.assertFalse(subscribed)
        self.assertEqual(updated, [1])

    async def test_ensure_websub_uses_target_subscription_when_id_is_given(self):
        requested: list[int] = []

        async def list_subscriptions():
            raise AssertionError("list_subscriptions should not be used")

        async def get_subscription(subscription_id):
            return _subscription(id=subscription_id, channel_id="UC_TARGET")

        async def request_subscription(subscription, *, callback_url, mode):
            requested.append(subscription.id)
            return True

        async def update_websub_state(*_args, **_kwargs):
            return None

        subscribed = await ensure_youtube_websub_subscription(
            callback_url="https://bot.example/youtube/websub?token=token",
            subscription_id=42,
            list_subscriptions=list_subscriptions,
            get_subscription=get_subscription,
            request_subscription=request_subscription,
            update_websub_state=update_websub_state,
        )

        self.assertTrue(subscribed)
        self.assertEqual(requested, [42])

    async def test_request_websub_subscription_posts_payload_and_handles_errors(self):
        session_factory = _SessionFactory(status=202, body="accepted")
        failed_session_factory = _SessionFactory(status=500, body="failed")
        logs: list[str] = []

        subscribed = await request_youtube_websub_subscription(
            _subscription(channel_id="UC_TEST"),
            callback_url="https://bot.example/youtube/websub?token=token",
            mode="subscribe",
            session_factory=session_factory,
            log=logs.append,
        )
        failed = await request_youtube_websub_subscription(
            _subscription(channel_id="UC_TEST"),
            callback_url="https://bot.example/youtube/websub?token=token",
            mode="subscribe",
            session_factory=failed_session_factory,
            log=logs.append,
        )

        self.assertTrue(subscribed)
        self.assertFalse(failed)
        self.assertEqual(
            session_factory.requests[0]["data"]["hub.topic"],
            "https://www.youtube.com/feeds/videos.xml?channel_id=UC_TEST",
        )
        self.assertIn("YouTube WebSub 요청 실패", logs[0])

    async def test_unsubscribe_uses_unsubscribe_mode(self):
        requested: list[tuple[int, str]] = []

        async def request_subscription(subscription, *, callback_url, mode):
            requested.append((subscription.id, mode))
            return True

        unsubscribed = await unsubscribe_youtube_websub_subscription(
            _subscription(id=7),
            callback_url="https://bot.example/youtube/websub?token=token",
            request_subscription=request_subscription,
        )

        self.assertTrue(unsubscribed)
        self.assertEqual(requested, [(7, "unsubscribe")])


class _SessionFactory:
    def __init__(self, *, status: int, body: str):
        self.status = status
        self.body = body
        self.requests: list[dict] = []

    def __call__(self, **_kwargs):
        return _Session(self)


class _Session:
    def __init__(self, factory: _SessionFactory):
        self.factory = factory

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, data):
        self.factory.requests.append({"url": url, "data": data})
        return _Response(self.factory.status, self.factory.body)


class _Response:
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self.body


if __name__ == "__main__":
    unittest.main()
