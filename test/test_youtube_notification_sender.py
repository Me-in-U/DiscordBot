import unittest
from pathlib import Path

from util.youtube.notification_sender import (
    resolve_youtube_notification_target,
    send_youtube_live_notification,
    send_youtube_upload_notification,
)
from util.youtube_subscriptions import YouTubeSubscription
from util.youtube_websub import YouTubeVideoLiveStatus, YouTubeVideoStatus


YOUTUBE_NOTIFICATION_SENDER_PATH = Path("util/youtube/notification_sender.py")
LEGACY_YOUTUBE_NOTIFICATION_SENDER_PATH = Path("util/youtube_notification_sender.py")


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


def _status(video_id: str, title: str = "영상") -> YouTubeVideoLiveStatus:
    return YouTubeVideoLiveStatus(
        video_id=video_id,
        channel_id="UC_TEST",
        title=title,
        status=YouTubeVideoStatus.UPLOAD,
    )


class YouTubeNotificationSenderTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_notification_sender_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_NOTIFICATION_SENDER_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_NOTIFICATION_SENDER_PATH.exists())

    async def test_resolves_configured_channel_from_cache(self):
        channel = _Channel()
        bot = _Bot(cached_channel=channel)
        logs: list[str] = []

        target = await resolve_youtube_notification_target(
            bot,
            _subscription(),
            "영상",
            get_channel_setting=_setting(123),
            log=logs.append,
        )

        self.assertIs(target, channel)
        self.assertEqual(bot.fetched_channel_ids, [])
        self.assertEqual(logs, [])

    async def test_live_notification_skips_already_notified_video(self):
        channel = _Channel()
        sent = await send_youtube_live_notification(
            _Bot(cached_channel=channel),
            _subscription(notified_video_ids=["live-1"]),
            _status("live-1"),
            get_channel_setting=_setting(123),
        )

        self.assertFalse(sent)
        self.assertEqual(channel.messages, [])

    async def test_upload_notification_sends_message_to_resolved_channel(self):
        channel = _Channel()

        sent = await send_youtube_upload_notification(
            _Bot(cached_channel=channel),
            _subscription(channel_name="업로드 채널"),
            _status("upload-1", title="새 영상"),
            get_channel_setting=_setting(123),
        )

        self.assertTrue(sent)
        self.assertEqual(
            channel.messages,
            ["## 📺 업로드 채널 새 영상\n**새 영상**\nhttps://youtu.be/upload-1"],
        )

    async def test_missing_channel_setting_logs_and_returns_none(self):
        logs: list[str] = []

        target = await resolve_youtube_notification_target(
            _Bot(cached_channel=_Channel()),
            _subscription(),
            "라이브",
            get_channel_setting=_setting(None),
            log=logs.append,
        )

        self.assertIsNone(target)
        self.assertEqual(
            logs,
            ["YouTube 라이브 알림 채널이 설정되지 않았습니다. guild=10 channel=UC_TEST"],
        )


class _Channel:
    def __init__(self):
        self.messages: list[str] = []

    async def send(self, message: str) -> None:
        self.messages.append(message)


class _Bot:
    def __init__(self, *, cached_channel):
        self.cached_channel = cached_channel
        self.fetched_channel_ids: list[int] = []

    def get_channel(self, channel_id: int):
        return self.cached_channel if channel_id == 123 else None

    async def fetch_channel(self, channel_id: int):
        self.fetched_channel_ids.append(channel_id)
        return self.cached_channel


def _setting(channel_id):
    async def get_channel_setting(_guild_id: int, _purpose: str):
        return channel_id

    return get_channel_setting


if __name__ == "__main__":
    unittest.main()
