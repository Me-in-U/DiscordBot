import collections
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace

from util.music_queue import QueuedTrack


MUSIC_EMBEDS_PATH = Path("util/music/embeds.py")
LEGACY_MUSIC_EMBEDS_PATH = Path("util/music_embeds.py")


with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="'audioop' is deprecated and slated for removal in Python 3.13",
        category=DeprecationWarning,
    )
    from util.music.embeds import make_default_music_embed, make_playing_music_embed


class _Avatar:
    url = "https://example.com/requester.png"


class _Requester:
    display_name = "신청자"
    display_avatar = _Avatar()


class _Player:
    title = "테스트 곡"
    requester = _Requester()
    data = {
        "duration": 120,
        "thumbnail": "https://example.com/thumb.png",
    }


class MusicEmbedHelperTests(unittest.TestCase):
    def test_embed_helper_lives_under_music_package(self):
        self.assertTrue(MUSIC_EMBEDS_PATH.exists())
        self.assertFalse(LEGACY_MUSIC_EMBEDS_PATH.exists())

    def test_default_embed_contains_music_panel_help_and_footer_icon(self):
        embed = make_default_music_embed(bot_avatar_url="https://example.com/bot.png")
        data = embed.to_dict()

        self.assertEqual(data["title"], "🎵 신창섭의 다해줬잖아")
        self.assertEqual(data["fields"][0]["name"], "❓ 사용법")
        self.assertIn("/재생 <URL/검색어>", data["fields"][0]["value"])
        self.assertEqual(data["footer"]["icon_url"], "https://example.com/bot.png")

    def test_playing_embed_contains_progress_queue_and_playback_footer(self):
        queue = collections.deque(
            [
                QueuedTrack(url="https://example.com/1", title="노래1"),
                QueuedTrack(url="https://example.com/2", title="노래2"),
                QueuedTrack(url="https://example.com/3", title="노래3"),
            ]
        )

        embed = make_playing_music_embed(
            _Player(),
            queue=queue,
            is_loop=True,
            is_paused=True,
            elapsed=30,
            fallback_requester_icon_url="https://example.com/bot.png",
        )
        data = embed.to_dict()

        self.assertEqual([field["name"] for field in data["fields"]], ["곡 제목", "진행", "대기열(3개)"])
        self.assertEqual(data["fields"][0]["value"], "테스트 곡")
        self.assertIn("00:30", data["fields"][1]["value"])
        self.assertIn("02:00", data["fields"][1]["value"])
        self.assertEqual(data["fields"][2]["value"], "`1` 노래1\n`2` 노래2\n`3` 노래3")
        self.assertEqual(data["thumbnail"]["url"], "https://example.com/thumb.png")
        self.assertIn("반복: 켜짐", data["footer"]["text"])
        self.assertIn("일시정지 상태", data["footer"]["text"])
        self.assertEqual(data["footer"]["icon_url"], "https://example.com/requester.png")

    def test_playing_embed_uses_fallback_requester_when_requester_is_missing(self):
        player = SimpleNamespace(
            title="제목 없음",
            requester=None,
            data={"duration": 0, "thumbnail": None},
        )

        embed = make_playing_music_embed(
            player,
            queue=[],
            is_loop=False,
            is_paused=False,
            elapsed=0,
            fallback_requester_icon_url="https://example.com/bot.png",
        )
        footer = embed.to_dict()["footer"]

        self.assertIn("신청자: 알 수 없음", footer["text"])
        self.assertIn("반복: 꺼짐", footer["text"])
        self.assertIn("재생중", footer["text"])
        self.assertEqual(footer["icon_url"], "https://example.com/bot.png")
