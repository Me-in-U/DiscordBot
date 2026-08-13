from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Collection, Sequence


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


@dataclass(frozen=True, slots=True)
class LolScrimParticipant:
    user_id: int
    label: str


class LolScrimRoster:
    def __init__(self) -> None:
        self._participants: dict[int, LolScrimParticipant] = {}

    @property
    def count(self) -> int:
        return len(self._participants)

    @property
    def is_full(self) -> bool:
        return self.count == MAX_SCRIM_PLAYERS

    def contains(self, user_id: int) -> bool:
        return user_id in self._participants

    def add(self, user_id: int, label: str) -> bool:
        if self.contains(user_id):
            return False
        if self.is_full:
            raise ValueError("내전 참가자는 최대 10명까지 등록할 수 있습니다.")

        normalized_label = str(label).strip()
        if not normalized_label:
            raise ValueError("내전 참가자 이름은 비어 있을 수 없습니다.")

        self._participants[user_id] = LolScrimParticipant(
            user_id=user_id,
            label=normalized_label,
        )
        return True

    def remove(self, user_id: int) -> bool:
        return self._participants.pop(user_id, None) is not None

    def retain(self, user_ids: Collection[int]) -> list[int]:
        retained_user_ids = set(user_ids)
        removed_user_ids = [
            user_id
            for user_id in self._participants
            if user_id not in retained_user_ids
        ]
        for user_id in removed_user_ids:
            del self._participants[user_id]
        return removed_user_ids

    def labels(self) -> list[str]:
        return [participant.label for participant in self._participants.values()]


def build_lol_scrim_match(
    players: Sequence[str],
    *,
    rng: random.Random | None = None,
) -> LolScrimMatch:
    players = [
        str(player).strip()
        for player in players
        if str(player).strip()
    ]
    if len(players) != MAX_SCRIM_PLAYERS:
        raise ValueError("내전 팀 배정에는 정확히 10명이 필요합니다.")

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


def format_lol_scrim_roster(
    participant_labels: Sequence[str],
    *,
    max_players: int = MAX_SCRIM_PLAYERS,
) -> str:
    if len(participant_labels) > max_players:
        raise ValueError("표시할 참가자가 모집 정원을 초과했습니다.")

    lines = [
        f"`{index:02d}` {label}"
        for index, label in enumerate(participant_labels, start=1)
    ]
    lines.extend(
        f"`{index:02d}` 빈자리"
        for index in range(len(participant_labels) + 1, max_players + 1)
    )
    return "\n".join(lines)


def format_lol_scrim_match(match: LolScrimMatch) -> str:
    red_lines = format_lol_scrim_team_slots(match.red)
    blue_lines = format_lol_scrim_team_slots(match.blue)
    return f"## 롤 내전 팀 배정\n\n### 레드팀\n{red_lines}\n\n### 블루팀\n{blue_lines}"
