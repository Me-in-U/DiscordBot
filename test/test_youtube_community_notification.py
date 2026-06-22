import unittest
from pathlib import Path

from util.youtube.community import YouTubeCommunityPost
from util.youtube.community_notification import (
    mark_youtube_community_post_notified,
    process_youtube_community_notifications,
    send_youtube_community_notification,
)
from util.youtube_subscriptions import YouTubeSubscription


YOUTUBE_COMMUNITY_NOTIFICATION_PATH = Path("util/youtube/community_notification.py")
LEGACY_YOUTUBE_COMMUNITY_NOTIFICATION_PATH = Path(
    "util/youtube_community_notification.py"
)


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


def _post(post_id: str, *, text: str = "본문") -> YouTubeCommunityPost:
    return YouTubeCommunityPost(
        post_id=post_id,
        url=f"https://youtube.com/post/{post_id}",
        author="작성자",
        published_time="1시간 전",
        text=text,
        attachment_urls=["https://i.ytimg.com/post/image.jpg"],
    )


class YouTubeCommunityNotificationTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_community_notification_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_COMMUNITY_NOTIFICATION_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_COMMUNITY_NOTIFICATION_PATH.exists())

    async def test_mark_community_post_notified_trims_ids_and_persists_state(self):
        recorder = _Recorder()
        subscription = _subscription(
            notified_community_post_ids=[f"post-{index}" for index in range(30)]
        )

        updated = await mark_youtube_community_post_notified(
            subscription,
            "post-new",
            update_community_state=recorder.update_community_state,
        )

        self.assertEqual(updated.notified_community_post_ids[-1], "post-new")
        self.assertEqual(len(updated.notified_community_post_ids), 30)
        self.assertNotIn("post-0", updated.notified_community_post_ids)
        self.assertEqual(
            recorder.calls,
            [
                (
                    1,
                    {
                        "notified_community_post_ids": (
                            updated.notified_community_post_ids
                        )
                    },
                )
            ],
        )

    async def test_send_community_notification_builds_embed_and_message(self):
        channel = _Channel()

        sent = await send_youtube_community_notification(
            _Bot(cached_channel=channel),
            _subscription(),
            _post("post-1", text=""),
            get_channel_setting=_setting(123),
        )

        self.assertTrue(sent)
        self.assertEqual(
            channel.messages[0]["content"],
            "## 📝 커뮤니티 채널 새 커뮤니티 게시물\nhttps://youtube.com/post/post-1",
        )
        embed = channel.messages[0]["embed"]
        self.assertEqual(embed.title, "커뮤니티 채널 커뮤니티 게시물")
        self.assertEqual(embed.description, "본문 없음")
        self.assertEqual(embed.url, "https://youtube.com/post/post-1")
        self.assertEqual(embed.author.name, "작성자")
        self.assertEqual(embed.fields[0].name, "게시 시각")
        self.assertEqual(embed.fields[0].value, "1시간 전")
        self.assertEqual(embed.image.url, "https://i.ytimg.com/post/image.jpg")

    async def test_send_community_notification_skips_already_notified_post(self):
        channel = _Channel()

        sent = await send_youtube_community_notification(
            _Bot(cached_channel=channel),
            _subscription(notified_community_post_ids=["post-1"]),
            _post("post-1"),
            get_channel_setting=_setting(123),
        )

        self.assertFalse(sent)
        self.assertEqual(channel.messages, [])

    async def test_process_community_notifications_seeds_first_seen_posts(self):
        channel = _Channel()
        recorder = _Recorder()

        updated = await process_youtube_community_notifications(
            _Bot(cached_channel=channel),
            _subscription(notified_community_post_ids=[]),
            [_post("post-new"), _post("post-old")],
            get_channel_setting=_setting(123),
            update_community_state=recorder.update_community_state,
        )

        self.assertEqual(updated.notified_community_post_ids, ["post-new", "post-old"])
        self.assertEqual(channel.messages, [])
        self.assertEqual(
            recorder.calls,
            [(1, {"notified_community_post_ids": ["post-new", "post-old"]})],
        )

    async def test_process_community_notifications_sends_new_posts_oldest_first(self):
        channel = _Channel()
        recorder = _Recorder()

        updated = await process_youtube_community_notifications(
            _Bot(cached_channel=channel),
            _subscription(notified_community_post_ids=["post-seen"]),
            [_post("post-new"), _post("post-old")],
            get_channel_setting=_setting(123),
            update_community_state=recorder.update_community_state,
        )

        self.assertEqual(
            [message["content"].splitlines()[-1] for message in channel.messages],
            ["https://youtube.com/post/post-old", "https://youtube.com/post/post-new"],
        )
        self.assertEqual(
            updated.notified_community_post_ids,
            ["post-seen", "post-old", "post-new"],
        )


class _Recorder:
    def __init__(self):
        self.calls: list[tuple[int, dict]] = []

    async def update_community_state(self, subscription_id: int, **kwargs) -> None:
        self.calls.append((subscription_id, kwargs))


class _Channel:
    def __init__(self):
        self.messages: list[dict] = []

    async def send(self, *, content=None, embed=None) -> None:
        self.messages.append({"content": content, "embed": embed})


class _Bot:
    def __init__(self, *, cached_channel):
        self.cached_channel = cached_channel

    def get_channel(self, channel_id: int):
        return self.cached_channel if channel_id == 123 else None

    async def fetch_channel(self, channel_id: int):
        return self.cached_channel


def _setting(channel_id):
    async def get_channel_setting(_guild_id: int, _purpose: str):
        return channel_id

    return get_channel_setting


if __name__ == "__main__":
    unittest.main()
