from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from util.db import execute_query, fetch_all, fetch_one


MUSIC_FAVORITE_SLOT_MIN = 1
MUSIC_FAVORITE_SLOT_MAX = 5
MUSIC_FAVORITE_BUTTON_TITLE_LIMIT = 12


@dataclass(frozen=True, slots=True)
class MusicFavorite:
    guild_id: int
    slot: int
    title: str
    url: str
    duration: int = 0
    uploader: str | None = None
    thumbnail: str | None = None
    updated_by: int | None = None


def validate_music_favorite_slot(slot: int) -> int:
    slot = int(slot)
    if slot < MUSIC_FAVORITE_SLOT_MIN or slot > MUSIC_FAVORITE_SLOT_MAX:
        raise ValueError("즐겨찾기 번호는 1~5 사이여야 합니다.")
    return slot


def row_to_music_favorite(row: dict[str, Any]) -> MusicFavorite:
    return MusicFavorite(
        guild_id=int(row["guild_id"]),
        slot=int(row["slot"]),
        title=str(row.get("title") or "(제목 정보 없음)"),
        url=str(row.get("url") or ""),
        duration=int(row.get("duration") or 0),
        uploader=row.get("uploader"),
        thumbnail=row.get("thumbnail"),
        updated_by=int(row["updated_by"]) if row.get("updated_by") else None,
    )


def shorten_music_favorite_title(
    title: str | None,
    *,
    limit: int = MUSIC_FAVORITE_BUTTON_TITLE_LIMIT,
) -> str:
    text = (title or "(제목 정보 없음)").strip() or "(제목 정보 없음)"
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def build_music_favorite_button_label(
    slot: int,
    favorite: MusicFavorite | None,
) -> str:
    validate_music_favorite_slot(slot)
    if favorite is None:
        return f"{slot} 빈칸"
    return f"{slot} {shorten_music_favorite_title(favorite.title)}"


def current_player_to_music_favorite(
    guild_id: int,
    player: object | None,
    *,
    slot: int = 1,
) -> MusicFavorite | None:
    if player is None:
        return None

    raw_data = getattr(player, "data", {})
    data: Mapping[str, Any] = raw_data if isinstance(raw_data, Mapping) else {}
    url = (getattr(player, "webpage_url", None) or data.get("webpage_url") or "")
    clean_url = str(url).strip()
    if not clean_url:
        return None

    raw_title = getattr(player, "title", None) or data.get("title") or ""
    clean_title = str(raw_title).strip() or "(제목 정보 없음)"
    try:
        duration = int(data.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0

    return MusicFavorite(
        guild_id=int(guild_id),
        slot=validate_music_favorite_slot(slot),
        title=clean_title,
        url=clean_url,
        duration=duration,
        uploader=data.get("uploader"),
        thumbnail=data.get("thumbnail"),
    )


async def list_music_favorites(guild_id: int) -> list[MusicFavorite]:
    rows = await fetch_all(
        """
        SELECT guild_id, slot, title, url, duration, uploader, thumbnail, updated_by
        FROM music_favorites
        WHERE guild_id = %s
        ORDER BY slot
        """,
        (int(guild_id),),
    )
    return [row_to_music_favorite(row) for row in rows]


async def get_music_favorite(guild_id: int, slot: int) -> MusicFavorite | None:
    slot = validate_music_favorite_slot(slot)
    row = await fetch_one(
        """
        SELECT guild_id, slot, title, url, duration, uploader, thumbnail, updated_by
        FROM music_favorites
        WHERE guild_id = %s AND slot = %s
        """,
        (int(guild_id), slot),
    )
    return row_to_music_favorite(row) if row else None


async def upsert_music_favorite(
    *,
    guild_id: int,
    slot: int,
    title: str,
    url: str,
    duration: int = 0,
    uploader: str | None = None,
    thumbnail: str | None = None,
    updated_by: int | None = None,
) -> None:
    slot = validate_music_favorite_slot(slot)
    clean_title = (title or "").strip() or "(제목 정보 없음)"
    clean_url = (url or "").strip()
    if not clean_url:
        raise ValueError("즐겨찾기에 저장할 URL이 없습니다.")

    await execute_query(
        """
        INSERT INTO music_favorites (
            guild_id, slot, title, url, duration, uploader, thumbnail, updated_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            title = VALUES(title),
            url = VALUES(url),
            duration = VALUES(duration),
            uploader = VALUES(uploader),
            thumbnail = VALUES(thumbnail),
            updated_by = VALUES(updated_by),
            updated_at = CURRENT_TIMESTAMP(6)
        """,
        (
            int(guild_id),
            slot,
            clean_title,
            clean_url,
            int(duration or 0),
            uploader,
            thumbnail,
            int(updated_by) if updated_by else None,
        ),
    )
