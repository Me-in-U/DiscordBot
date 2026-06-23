from __future__ import annotations

import logging

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from util.env_utils import getenv_clean

logger = logging.getLogger(__name__)


class YouTubeApiError(Exception):
    """Raised when YouTube Data API calls fail or return unusable data."""


def _build_youtube_client():
    return build("youtube", "v3", developerKey=getenv_clean("GOOGLE_API_KEY"))


def fetch_video_title(video_id: str) -> str:
    if not video_id:
        raise YouTubeApiError("유효한 유튜브 영상 ID가 없습니다.")

    try:
        youtube = _build_youtube_client()
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        items = response.get("items", [])
        if not items:
            raise YouTubeApiError("유튜브 영상 정보를 찾지 못했습니다.")

        title = str(items[0].get("snippet", {}).get("title", "")).strip()
        if not title:
            raise YouTubeApiError("유튜브 영상 제목이 비어 있습니다.")
        return title
    except YouTubeApiError:
        raise
    except (HttpError, KeyError, TypeError, ValueError) as exc:
        raise YouTubeApiError("유튜브 영상 제목을 조회하지 못했습니다.") from exc


def is_live_video(video_id: str) -> bool:
    try:
        youtube = _build_youtube_client()
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        items = response.get("items", [])
        if not items:
            return False

        live_broadcast_content = items[0]["snippet"].get("liveBroadcastContent", "none")
        return live_broadcast_content in {"live", "upcoming"}
    except (HttpError, KeyError, TypeError, ValueError) as exc:
        raise YouTubeApiError("유튜브 라이브 상태를 조회하지 못했습니다.") from exc


def fetch_youtube_comments(video_id: str, max_comments: int = 10) -> list[str]:
    try:
        youtube = _build_youtube_client()
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_comments,
            textFormat="plainText",
        )
        response = request.execute()
        comments = []
        for item in response.get("items", []):
            comment = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(comment)
        return comments
    except (HttpError, KeyError, TypeError, ValueError) as exc:
        logger.warning("YouTube 댓글 가져오기 오류: video_id=%s", video_id, exc_info=True)
        raise YouTubeApiError("유튜브 댓글을 조회하지 못했습니다.") from exc
