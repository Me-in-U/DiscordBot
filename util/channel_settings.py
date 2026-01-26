from __future__ import annotations
from typing import Dict, Optional
from .db import execute_query, fetch_one, fetch_all


async def get_channel(guild_id: int, purpose: str) -> Optional[int]:
    query = "SELECT channel_id FROM channel_settings WHERE guild_id = %s AND channel_type = %s"
    row = await fetch_one(query, (str(guild_id), purpose))
    if row:
        return int(row["channel_id"])
    return None


async def set_channel(guild_id: int, purpose: str, channel_id: Optional[int]) -> None:
    if channel_id is None:
        query = "DELETE FROM channel_settings WHERE guild_id = %s AND channel_type = %s"
        await execute_query(query, (str(guild_id), purpose))
    else:
        # Check if exists to update or insert (MySQL UPSERT)
        query = """
            INSERT INTO channel_settings (guild_id, channel_type, channel_id) 
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE channel_id = VALUES(channel_id)
        """
        await execute_query(query, (str(guild_id), purpose, str(channel_id)))


async def get_channels_by_purpose(purpose: str) -> Dict[int, int]:
    query = "SELECT guild_id, channel_id FROM channel_settings WHERE channel_type = %s"
    rows = await fetch_all(query, (purpose,))
    result = {}
    for row in rows:
        try:
            result[int(row["guild_id"])] = int(row["channel_id"])
        except ValueError:
            continue
    return result


async def get_settings_for_guild(guild_id: int) -> Dict[str, int]:
    query = "SELECT channel_type, channel_id FROM channel_settings WHERE guild_id = %s"
    rows = await fetch_all(query, (str(guild_id),))
    return {row["channel_type"]: int(row["channel_id"]) for row in rows}
