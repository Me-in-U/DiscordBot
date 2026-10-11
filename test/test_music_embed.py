import collections
import unittest

from cogs.music import MusicCog, QueuedTrack


class _Avatar:
    url = "https://example.com/avatar.png"


class _BotUser:
    avatar = None
    display_avatar = _Avatar()


class _Bot:
    user = _BotUser()


class _Player:
    title = "[출근용 봄노래] 장범준(버스커버스커) - 🎧봄노래 모음"
    webpage_url = "https://example.com/current"
    requester = None
    data = {
        "title": title,
        "duration": 1673,
        "thumbnail": "https://example.com/thumb.png",
    }


class MusicEmbedTests(unittest.TestCase):
    def test_default_embed_supports_bot_without_custom_avatar(self):
        cog = MusicCog(_Bot())
        embed = cog._make_default_embed()
        self.assertEqual(embed.footer.icon_url, _Avatar.url)


    def test_playing_embed_adds_queue_preview_after_progress(self):
        cog = MusicCog(_Bot())
        state = cog._get_state(1)
        state.queue = collections.deque(
            [
                QueuedTrack(url="https://example.com/1", title="노래1"),
                QueuedTrack(url="https://example.com/2", title="노래2"),
                QueuedTrack(url="https://example.com/3", title="노래3"),
                QueuedTrack(url="https://example.com/4", title="노래4"),
            ]
        )

        embed = cog._make_playing_embed(_Player(), 1, elapsed=95)

        fields = embed.to_dict()["fields"]
        self.assertEqual([field["name"] for field in fields], ["곡 제목", "재생 중", "대기열(4개)"])
        self.assertEqual(
            fields[0]["value"],
            "[출근용 봄노래] 장범준(버스커버스커) - 🎧봄노래 모음",
        )
        self.assertEqual(fields[1]["value"], "━●━━━━━━━━━━━━━━━━━\n01:35 / 27:53    5%")
        self.assertEqual(fields[2]["value"], "`1` 노래1\n`2` 노래2\n`3` 노래3\n+ 1곡 더")

    def test_paused_embed_labels_progress_without_duplicate_bar(self):
        cog = MusicCog(_Bot())
        cog._get_state(1).paused_at = 123.0
        field = cog._make_playing_embed(_Player(), 1, elapsed=95).to_dict()["fields"][1]
        self.assertEqual(field["name"], "일시정지")
        self.assertEqual(field["value"].count("●"), 1)
        self.assertNotIn("▱", field["value"])


if __name__ == "__main__":
    unittest.main()
