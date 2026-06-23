from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def count_cached_user_messages(user_messages: Mapping[Any, Any]) -> int:
    total_messages = 0
    for guild_map in user_messages.values():
        if not isinstance(guild_map, dict):
            continue
        for messages in guild_map.values():
            if isinstance(messages, list):
                total_messages += len(messages)
    return total_messages


def build_presence_activity_name(user_messages: Mapping[Any, Any]) -> str:
    total_messages = count_cached_user_messages(user_messages)
    return f"/도움 | {total_messages:,}개의 채팅 메시지 보관"
