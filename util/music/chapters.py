from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MusicChapter:
    title: str
    start_time: int


def music_chapters(data: dict) -> list[MusicChapter]:
    if data.get("is_live"):
        return []
    chapters = {}
    for entry in data.get("chapters") or []:
        if not isinstance(entry, dict):
            continue
        try:
            start = float(entry["start_time"])
            duration = float(data.get("duration") or 0)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(start) or start < 0 or (duration > 0 and start >= duration):
            continue
        seconds = int(start)
        title = str(entry.get("title") or f"챕터 {len(chapters) + 1}").strip()
        chapters.setdefault(seconds, MusicChapter(title or "챕터", seconds))
    return [chapters[start] for start in sorted(chapters)]


def current_chapter_index(chapters: list[MusicChapter], elapsed: float) -> int:
    return next((index for index in range(len(chapters) - 1, -1, -1)
                 if chapters[index].start_time <= elapsed), -1)
