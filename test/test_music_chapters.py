import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from util.music.chapters import current_chapter_index, music_chapters
from util.music.embeds import make_playing_music_embed
from util.music.state import GuildMusicState
from util.music.views import MusicControlView


CHAPTER_DATA = {"duration": 180, "chapters": [
    {"title": "처음", "start_time": 0},
    {"title": "중간", "start_time": 60},
    {"title": "마지막", "start_time": 120},
]}


class ChapterTests(unittest.IsolatedAsyncioTestCase):
    def test_unsorted_duplicate_and_invalid_external_chapters(self):
        chapters = music_chapters({"duration": 180, "chapters": [
            {"title": "중간", "start_time": 60.9},
            {"title": "처음", "start_time": 0},
            {"title": "중복", "start_time": 60},
            {"start_time": -1}, {"start_time": float("nan")},
            {"start_time": float("inf")}, {"start_time": 180},
            {"start_time": None}, {}, None,
        ]})
        self.assertEqual([(c.title, c.start_time) for c in chapters], [("처음", 0), ("중간", 60)])
        self.assertEqual(current_chapter_index(chapters, 59), 0)
        self.assertEqual(current_chapter_index(chapters, 60), 1)
        self.assertEqual(current_chapter_index(chapters, -1), -1)
        self.assertEqual(music_chapters({**CHAPTER_DATA, "is_live": True}), [])
        self.assertEqual(music_chapters({}), [])

    async def test_paused_panel_shows_adjacent_names_and_invokes_relative_navigation(self):
        player = SimpleNamespace(data=CHAPTER_DATA)
        state = GuildMusicState(player=player, start_ts=100, paused_at=175)
        cog = SimpleNamespace(_seek_chapter=AsyncMock())
        view = MusicControlView(cog, state)
        buttons = [b for b in view.children if b.custom_id.startswith("music_chapter_")]
        self.assertEqual([b.label for b in buttons], ["◀ 처음", "마지막 ▶"])
        await buttons[1].callback("interaction")
        cog._seek_chapter.assert_awaited_once_with("interaction", 1, player)

    async def test_first_and_last_chapter_disable_unavailable_direction(self):
        player = SimpleNamespace(data=CHAPTER_DATA)
        for elapsed, disabled in ((0, [True, False]), (120, [False, True])):
            with self.subTest(elapsed=elapsed):
                view = MusicControlView(object(), GuildMusicState(player=player, start_ts=100, paused_at=100 + elapsed))
                buttons = [b for b in view.children if b.custom_id.startswith("music_chapter_")]
                self.assertEqual([b.disabled for b in buttons], disabled)
                self.assertTrue(all(len(b.label) <= 80 for b in buttons))

    def test_embed_shows_current_chapter(self):
        player = SimpleNamespace(title="모음집", data=CHAPTER_DATA, requester=None)
        embed = make_playing_music_embed(player, queue=[], is_loop=False,
            is_paused=False, elapsed=75, fallback_requester_icon_url="https://example.com/avatar.png")
        field = next(f for f in embed.fields if f.name.startswith("챕터"))
        self.assertEqual((field.name, field.value), ("챕터 2/3", "중간"))
