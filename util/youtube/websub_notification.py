from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from util.youtube_subscriptions import (
    YouTubeSubscription,
    find_youtube_subscriptions_by_channel_id,
)
from util.youtube_websub import parse_youtube_atom_entries


FindSubscriptions = Callable[[str], Awaitable[Sequence[YouTubeSubscription]]]
ProcessVideoCandidate = Callable[[YouTubeSubscription, str], Awaitable[str]]


async def handle_youtube_websub_notification(
    atom_xml: str,
    *,
    process_video_candidate: ProcessVideoCandidate,
    find_subscriptions: FindSubscriptions = find_youtube_subscriptions_by_channel_id,
) -> dict[str, Any]:
    entries = parse_youtube_atom_entries(atom_xml)

    result: dict[str, Any] = {
        "received": len(entries),
        "processed": 0,
        "ignored": 0,
        "results": [],
    }
    for entry in entries:
        subscriptions = await find_subscriptions(entry.channel_id)
        if not subscriptions:
            result["ignored"] += 1
            continue

        for subscription in subscriptions:
            outcome = await process_video_candidate(subscription, entry.video_id)
            result["processed"] += 1
            result["results"].append(
                {
                    "guild_id": subscription.guild_id,
                    "subscription_id": subscription.id,
                    "video_id": entry.video_id,
                    "status": outcome,
                }
            )

    return result
