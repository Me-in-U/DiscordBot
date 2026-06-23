from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from typing import Any

from util.db import execute_query as default_execute_query
from util.db import fetch_all as default_fetch_all


PanelIdMap = dict[str, int]
FetchAll = Callable[[str], Awaitable[Sequence[dict[str, Any]]]]
ExecuteQuery = Callable[[str, tuple[int, ...]], Awaitable[Any]]

SELECT_PANEL_IDS_QUERY = "SELECT guild_id, message_id FROM panel_messages"
UPSERT_PANEL_ID_QUERY = (
    "INSERT INTO panel_messages (guild_id, message_id) VALUES (%s, %s) "
    "ON DUPLICATE KEY UPDATE message_id = %s"
)
DELETE_PANEL_ID_QUERY = "DELETE FROM panel_messages WHERE guild_id = %s"


def rows_to_music_panel_ids(rows: Sequence[dict[str, Any]]) -> PanelIdMap:
    return {str(row["guild_id"]): int(row["message_id"]) for row in rows}


async def load_music_panel_ids(
    *,
    fetch_all: FetchAll = default_fetch_all,
) -> PanelIdMap:
    rows = await fetch_all(SELECT_PANEL_IDS_QUERY)
    return rows_to_music_panel_ids(rows)


async def save_music_panel_id(
    cache: MutableMapping[str, int],
    guild_id: int | str,
    message_id: int | str,
    *,
    execute_query: ExecuteQuery = default_execute_query,
) -> None:
    normalized_guild_id = int(guild_id)
    normalized_message_id = int(message_id)
    cache[str(guild_id)] = normalized_message_id
    await execute_query(
        UPSERT_PANEL_ID_QUERY,
        (normalized_guild_id, normalized_message_id, normalized_message_id),
    )


async def delete_music_panel_id(
    cache: MutableMapping[str, int],
    guild_id: int | str,
    *,
    execute_query: ExecuteQuery = default_execute_query,
) -> None:
    cache.pop(str(guild_id), None)
    await execute_query(DELETE_PANEL_ID_QUERY, (int(guild_id),))
