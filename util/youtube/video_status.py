from __future__ import annotations

import asyncio
from typing import Any, Protocol

from util.youtube_websub import YouTubeVideoLiveStatus, classify_video_item


class YouTubeVideosListRequest(Protocol):
    def execute(self) -> dict[str, Any]: ...


class YouTubeVideosResource(Protocol):
    def list(self, **kwargs: Any) -> YouTubeVideosListRequest: ...


class YouTubeClient(Protocol):
    def videos(self) -> YouTubeVideosResource: ...


async def fetch_youtube_video_status(
    youtube: YouTubeClient,
    video_id: str,
) -> YouTubeVideoLiveStatus | None:
    def _fetch_video_item() -> dict[str, Any] | None:
        response = (
            youtube.videos()
            .list(
                part="snippet,liveStreamingDetails,status,contentDetails",
                id=video_id,
                maxResults=1,
            )
            .execute()
        )
        items = response.get("items", [])
        return items[0] if items else None

    item = await asyncio.to_thread(_fetch_video_item)
    return classify_video_item(item) if item else None
