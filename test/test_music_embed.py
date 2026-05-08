import collections
import unittest

from cogs.music import MusicCog, QueuedTrack


class _Avatar:
    url = "https://example.com/avatar.png"


class _BotUser:
    avatar = _Avatar()


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
        self.assertEqual([field["name"] for field in fields], ["곡 제목", "진행", "대기열(4개)"])
        self.assertEqual(
            fields[0]["value"],
            "[출근용 봄노래] 장범준(버스커버스커) - 🎧봄노래 모음",
        )
        self.assertTrue(fields[1]["value"].startswith("\n01:35"))
        self.assertEqual(fields[2]["value"], "`1` 노래1\n`2` 노래2\n`3` 노래3\n+ 1곡 더")


if __name__ == "__main__":
    unittest.main()
