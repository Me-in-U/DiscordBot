import random
import unittest
from pathlib import Path

from util.lol.scrim import (
    MAX_SCRIM_PLAYERS,
    TeamSlot,
    build_lol_scrim_match,
    format_lol_scrim_team_slots,
    parse_extra_players,
)


LOL_SCRIM_PATH = Path("util/lol/scrim.py")
LEGACY_LOL_SCRIM_PATH = Path("util/lol_scrim.py")


class LolScrimMatchTests(unittest.TestCase):
    def test_lol_scrim_lives_under_lol_package(self):
        self.assertTrue(LOL_SCRIM_PATH.exists())
        self.assertFalse(LEGACY_LOL_SCRIM_PATH.exists())

    def test_parse_extra_players_uses_commas_semicolons_and_newlines(self):
        self.assertEqual(
            parse_extra_players("추가1, 추가2; 추가3\n추가4"),
            ["추가1", "추가2", "추가3", "추가4"],
        )

    def test_parse_extra_players_treats_plain_text_as_one_player(self):
        self.assertEqual(parse_extra_players("친구 닉네임"), ["친구 닉네임"])

    def test_build_lol_scrim_match_fills_missing_slots(self):
        match = build_lol_scrim_match(
            ["A", "B", "C"],
            ["D"],
            rng=random.Random(7),
        )

        all_players = match.all_players()
        self.assertEqual(len(all_players), MAX_SCRIM_PLAYERS)
        self.assertIn("인원1", all_players)
        self.assertIn("인원6", all_players)
        self.assertEqual([slot.position for slot in match.red], ["탑", "정글", "미드", "원딜", "서폿"])
        self.assertEqual([slot.position for slot in match.blue], ["탑", "정글", "미드", "원딜", "서폿"])

    def test_build_lol_scrim_match_rejects_more_than_ten_players(self):
        with self.assertRaises(ValueError):
            build_lol_scrim_match(
                [f"유저{i}" for i in range(10)],
                ["추가1"],
                rng=random.Random(1),
            )

    def test_format_lol_scrim_team_slots_for_embed_field(self):
        self.assertEqual(
            format_lol_scrim_team_slots(
                [
                    TeamSlot("탑", "A"),
                    TeamSlot("정글", "B"),
                    TeamSlot("미드", "C"),
                    TeamSlot("원딜", "D"),
                    TeamSlot("서폿", "E"),
                ]
            ),
            "`탑` **A**\n`정글` **B**\n`미드` **C**\n`원딜` **D**\n`서폿` **E**",
        )


if __name__ == "__main__":
    unittest.main()
