from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Sequence


POSITIONS = ("탑", "정글", "미드", "원딜", "서폿")
MAX_SCRIM_PLAYERS = 10
TEAM_SIZE = 5


@dataclass(frozen=True, slots=True)
class TeamSlot:
    position: str
    player: str


@dataclass(frozen=True, slots=True)
class LolScrimMatch:
    red: tuple[TeamSlot, ...]
    blue: tuple[TeamSlot, ...]

    def all_players(self) -> list[str]:
        return [slot.player for slot in (*self.red, *self.blue)]


def parse_extra_players(text: str | None) -> list[str]:
    if not text:
        return []

    normalized = text.strip()
    if not normalized:
        return []

    if not re.search(r"[,;\n]", normalized):
        return [normalized]

    return [
        player.strip()
        for player in re.split(r"[,;\n]+", normalized)
        if player.strip()
    ]


def build_lol_scrim_match(
    voice_players: Sequence[str],
    extra_players: Sequence[str] | None = None,
    *,
    rng: random.Random | None = None,
) -> LolScrimMatch:
    players = [
        str(player).strip()
        for player in [*voice_players, *(extra_players or [])]
        if str(player).strip()
    ]
    if len(players) > MAX_SCRIM_PLAYERS:
        raise ValueError("내전 인원은 최대 10명까지 가능합니다.")

    missing_count = MAX_SCRIM_PLAYERS - len(players)
    players.extend(f"인원{index}" for index in range(1, missing_count + 1))

    randomizer = rng or random
    shuffled_players = list(players)
    randomizer.shuffle(shuffled_players)

    red_players = shuffled_players[:TEAM_SIZE]
    blue_players = shuffled_players[TEAM_SIZE:]
    return LolScrimMatch(
        red=tuple(
            TeamSlot(position, player)
            for position, player in zip(POSITIONS, red_players, strict=True)
        ),
        blue=tuple(
            TeamSlot(position, player)
            for position, player in zip(POSITIONS, blue_players, strict=True)
        ),
    )


def format_lol_scrim_team_slots(slots: Sequence[TeamSlot]) -> str:
    return "\n".join(f"`{slot.position}` **{slot.player}**" for slot in slots)


def format_lol_scrim_match(match: LolScrimMatch) -> str:
    red_lines = format_lol_scrim_team_slots(match.red)
    blue_lines = format_lol_scrim_team_slots(match.blue)
    return f"## 롤 내전 팀 배정\n\n### 레드팀\n{red_lines}\n\n### 블루팀\n{blue_lines}"
