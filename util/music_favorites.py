from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from util.db import execute_query, fetch_all, fetch_one
from util.music_search import normalize_search_entry_url


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


@dataclass(frozen=True, slots=True)
class MusicFavoriteCacheLoadAction:
    guild_id: int
    should_use_cache: bool
    cached_favorites: list[MusicFavorite] | None = None


@dataclass(frozen=True, slots=True)
class MusicFavoriteSavePayload:
    guild_id: int
    slot: int
    title: str
    url: str
    duration: int = 0
    uploader: str | None = None
    thumbnail: str | None = None
    updated_by: int | None = None

    @property
    def user_message(self) -> str:
        return f"⭐ {self.slot}번 즐겨찾기에 **{self.title}** 저장했습니다."


@dataclass(frozen=True, slots=True)
class MusicFavoriteSaveResult:
    guild_id: int
    user_message: str


@dataclass(frozen=True, slots=True)
class MusicFavoriteSaveResponseAction:
    guild_id: int
    user_message: str
    should_refresh_favorites: bool = True
    should_refresh_panel: bool = True


@dataclass(frozen=True, slots=True)
class MusicFavoritePanelRefreshAction:
    guild_id: int
    should_refresh: bool
    should_use_playing_panel: bool = False


@dataclass(frozen=True, slots=True)
class MusicFavoriteSearchEntrySaveAction:
    payload: MusicFavoriteSavePayload


@dataclass(frozen=True, slots=True)
class MusicFavoriteCurrentTrackSaveAction:
    slot: int
    payload: MusicFavoriteSavePayload | None = None
    user_message: str | None = None

    @property
    def should_save(self) -> bool:
        return self.payload is not None


@dataclass(frozen=True, slots=True)
class MusicFavoritePlayRequestAction:
    slot: int


@dataclass(frozen=True, slots=True)
class MusicFavoritePlayActionResult:
    slot: int
    should_play: bool
    user_message: str | None = None
    url: str | None = None
    success_prefix: str | None = None


@dataclass(frozen=True, slots=True)
class MusicFavoriteManagerSelectionAction:
    selected_slot: int
    selected_value: str
    status_text: str

    def is_default_value(self, value: object) -> bool:
        return str(value) == self.selected_value


@dataclass(frozen=True, slots=True)
class MusicFavoriteManagerOpenAction:
    guild_id: int
    favorites: list[MusicFavorite]
    current_track: MusicFavorite | None
    status_text: str


@dataclass(frozen=True, slots=True)
class MusicFavoriteSearchModalAction:
    slot: int


@dataclass(frozen=True, slots=True)
class MusicFavoriteSearchSubmitAction:
    slot: int
    query: str


@dataclass(frozen=True, slots=True)
class MusicFavoriteSearchRequestAction:
    slot: int
    query: str
    user_message: str | None = None

    @property
    def should_search(self) -> bool:
        return self.user_message is None


@dataclass(frozen=True, slots=True)
class MusicFavoriteCurrentSaveButtonAction:
    slot: int
    disabled: bool


def validate_music_favorite_slot(slot: int) -> int:
    slot = int(slot)
    if slot < MUSIC_FAVORITE_SLOT_MIN or slot > MUSIC_FAVORITE_SLOT_MAX:
        raise ValueError("즐겨찾기 번호는 1~5 사이여야 합니다.")
    return slot


def build_music_favorite_cache_load_action(
    *,
    guild_id: int | str,
    cache: Mapping[int, list[MusicFavorite]],
    refresh: bool = False,
) -> MusicFavoriteCacheLoadAction:
    normalized_guild_id = int(guild_id)
    if not refresh and normalized_guild_id in cache:
        return MusicFavoriteCacheLoadAction(
            guild_id=normalized_guild_id,
            should_use_cache=True,
            cached_favorites=cache[normalized_guild_id],
        )
    return MusicFavoriteCacheLoadAction(
        guild_id=normalized_guild_id,
        should_use_cache=False,
    )


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


def build_music_favorite_play_request_action(
    slot: int | str,
) -> MusicFavoritePlayRequestAction:
    return MusicFavoritePlayRequestAction(slot=validate_music_favorite_slot(slot))


def build_music_favorite_play_action(
    *,
    slot: int,
    favorite: MusicFavorite | None,
) -> MusicFavoritePlayActionResult:
    slot = validate_music_favorite_slot(slot)
    if favorite is None:
        return MusicFavoritePlayActionResult(
            slot=slot,
            should_play=False,
            user_message=f"❌ {slot}번 즐겨찾기가 비어있습니다.",
        )

    return MusicFavoritePlayActionResult(
        slot=slot,
        should_play=True,
        url=favorite.url,
        success_prefix="⭐ 즐겨찾기 재생",
    )


def build_music_favorite_manager_selection_action(
    selected_slot: int | str,
) -> MusicFavoriteManagerSelectionAction:
    slot = validate_music_favorite_slot(int(selected_slot))
    return MusicFavoriteManagerSelectionAction(
        selected_slot=slot,
        selected_value=str(slot),
        status_text=f"저장/수정할 즐겨찾기 슬롯: **{slot}번**",
    )


def build_music_favorite_manager_open_action(
    *,
    guild_id: int | str,
    favorites: list[MusicFavorite],
    player: object | None,
) -> MusicFavoriteManagerOpenAction:
    guild_id = int(guild_id)
    selection = build_music_favorite_manager_selection_action(1)
    return MusicFavoriteManagerOpenAction(
        guild_id=guild_id,
        favorites=list(favorites),
        current_track=current_player_to_music_favorite(guild_id, player),
        status_text=selection.status_text,
    )


def build_music_favorite_search_modal_action(
    slot: int | str,
) -> MusicFavoriteSearchModalAction:
    return MusicFavoriteSearchModalAction(slot=validate_music_favorite_slot(slot))


def build_music_favorite_search_submit_action(
    *,
    slot: int | str,
    query_value: object,
) -> MusicFavoriteSearchSubmitAction:
    return MusicFavoriteSearchSubmitAction(
        slot=validate_music_favorite_slot(slot),
        query=str(query_value or "").strip(),
    )


def build_music_favorite_search_request_action(
    *,
    slot: int | str,
    query_value: object,
) -> MusicFavoriteSearchRequestAction:
    slot = validate_music_favorite_slot(slot)
    query = str(query_value or "").strip()
    if not query:
        return MusicFavoriteSearchRequestAction(
            slot=slot,
            query="",
            user_message="❌ 검색어를 입력해 주세요.",
        )
    return MusicFavoriteSearchRequestAction(slot=slot, query=query)


def build_music_favorite_current_save_button_action(
    *,
    selected_slot: int | str,
    current_track: MusicFavorite | None,
) -> MusicFavoriteCurrentSaveButtonAction:
    return MusicFavoriteCurrentSaveButtonAction(
        slot=validate_music_favorite_slot(selected_slot),
        disabled=current_track is None,
    )


def build_music_favorite_current_track_save_action(
    *,
    current_track: MusicFavorite | None,
    slot: int | str,
    updated_by: int | None = None,
) -> MusicFavoriteCurrentTrackSaveAction:
    slot = validate_music_favorite_slot(slot)
    if current_track is None:
        return MusicFavoriteCurrentTrackSaveAction(
            slot=slot,
            user_message="❌ 현재 재생 중인 곡 정보가 없습니다.",
        )

    return MusicFavoriteCurrentTrackSaveAction(
        slot=slot,
        payload=music_favorite_to_save_payload(
            current_track,
            slot=slot,
            updated_by=updated_by,
        ),
    )


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


def build_music_favorite_save_payload(
    *,
    guild_id: int | str,
    slot: int | str,
    title: str | None,
    url: str | None,
    duration: Any = 0,
    uploader: str | None = None,
    thumbnail: str | None = None,
    updated_by: int | None = None,
) -> MusicFavoriteSavePayload:
    clean_title = (title or "").strip() or "(제목 정보 없음)"
    clean_url = (url or "").strip()
    if not clean_url:
        raise ValueError("즐겨찾기에 저장할 URL이 없습니다.")

    return MusicFavoriteSavePayload(
        guild_id=int(guild_id),
        slot=validate_music_favorite_slot(slot),
        title=clean_title,
        url=clean_url,
        duration=_safe_music_duration(duration),
        uploader=uploader or None,
        thumbnail=thumbnail or None,
        updated_by=int(updated_by) if updated_by else None,
    )


def search_entry_to_music_favorite_save_payload(
    *,
    guild_id: int | str,
    slot: int | str,
    entry: dict[str, Any],
    updated_by: int | None = None,
) -> MusicFavoriteSavePayload:
    return build_music_favorite_save_payload(
        guild_id=guild_id,
        slot=slot,
        title=entry.get("title") or None,
        url=normalize_search_entry_url(entry),
        duration=entry.get("duration") or 0,
        uploader=entry.get("uploader") or entry.get("channel") or None,
        thumbnail=_search_entry_thumbnail(entry),
        updated_by=updated_by,
    )


def build_music_favorite_search_entry_save_action(
    *,
    guild_id: int | str,
    slot: int | str,
    entry: dict[str, Any],
    updated_by: int | None = None,
) -> MusicFavoriteSearchEntrySaveAction:
    return MusicFavoriteSearchEntrySaveAction(
        payload=search_entry_to_music_favorite_save_payload(
            guild_id=guild_id,
            slot=slot,
            entry=entry,
            updated_by=updated_by,
        )
    )


def music_favorite_to_save_payload(
    favorite: MusicFavorite,
    *,
    slot: int | None = None,
    updated_by: int | None = None,
) -> MusicFavoriteSavePayload:
    return build_music_favorite_save_payload(
        guild_id=favorite.guild_id,
        slot=favorite.slot if slot is None else slot,
        title=favorite.title,
        url=favorite.url,
        duration=favorite.duration,
        uploader=favorite.uploader,
        thumbnail=favorite.thumbnail,
        updated_by=updated_by if updated_by is not None else favorite.updated_by,
    )


def _safe_music_duration(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _search_entry_thumbnail(entry: dict[str, Any]) -> str | None:
    thumbnail = entry.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail:
        return thumbnail

    thumbnails = entry.get("thumbnails") or []
    if isinstance(thumbnails, list) and thumbnails:
        candidate = thumbnails[-1]
        if isinstance(candidate, dict):
            candidate_url = candidate.get("url")
            return candidate_url if isinstance(candidate_url, str) else None

    return None


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


async def save_music_favorite_payload(
    payload: MusicFavoriteSavePayload,
) -> MusicFavoriteSaveResult:
    await upsert_music_favorite(
        guild_id=payload.guild_id,
        slot=payload.slot,
        title=payload.title,
        url=payload.url,
        duration=payload.duration,
        uploader=payload.uploader,
        thumbnail=payload.thumbnail,
        updated_by=payload.updated_by,
    )
    return MusicFavoriteSaveResult(
        guild_id=payload.guild_id,
        user_message=payload.user_message,
    )


def build_music_favorite_save_response_action(
    save_result: MusicFavoriteSaveResult,
) -> MusicFavoriteSaveResponseAction:
    return MusicFavoriteSaveResponseAction(
        guild_id=save_result.guild_id,
        user_message=save_result.user_message,
    )


def build_music_favorite_panel_refresh_action(
    *,
    guild_id: int | str,
    has_control_message: bool,
    has_control_channel: bool,
    has_player: bool,
) -> MusicFavoritePanelRefreshAction:
    should_refresh = bool(has_control_message and has_control_channel)
    return MusicFavoritePanelRefreshAction(
        guild_id=int(guild_id),
        should_refresh=should_refresh,
        should_use_playing_panel=should_refresh and bool(has_player),
    )
