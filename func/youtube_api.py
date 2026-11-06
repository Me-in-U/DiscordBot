from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

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


class YouTubeSummaryUnavailable(Exception):
    """A known video state that can be safely explained to the user."""


class YouTubeLiveInProgress(YouTubeSummaryUnavailable):
    """An active broadcast, silently ignored by automatic link prompts."""


def check_video_summary_available(video_id: str) -> None:
    try:
        youtube = _build_youtube_client()
        response = youtube.videos().list(
            part="snippet,liveStreamingDetails,status,contentDetails", id=video_id
        ).execute()
        items = response.get("items", [])
        if not items:
            raise YouTubeSummaryUnavailable(
                "영상을 조회할 수 없어 요약할 수 없습니다. 삭제, 비공개 또는 접근 제한 여부를 확인해 주세요."
            )

        item = items[0]
        snippet = item.get("snippet", {}) or {}
        live = item.get("liveStreamingDetails", {}) or {}
        status = item.get("status", {}) or {}
        broadcast = snippet.get("liveBroadcastContent", "none")
        if not live.get("actualEndTime") and (
            broadcast == "live" or live.get("actualStartTime")
        ):
            raise YouTubeLiveInProgress(
                "현재 라이브 또는 최초 공개가 진행 중이어서 요약할 수 없습니다. 종료 후 다시보기가 제공되면 다시 요청해 주세요."
            )
        scheduled = live.get("scheduledStartTime") or status.get("publishAt")
        if not live.get("actualStartTime") and not live.get("actualEndTime") and (
            broadcast == "upcoming" or scheduled
        ):
            schedule_text = "공개 예정 시간은 아직 제공되지 않았습니다."
            if scheduled:
                try:
                    start = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
                    if start.tzinfo is None:
                        raise ValueError("missing timezone")
                    kst = start.astimezone(timezone(timedelta(hours=9)))
                    schedule_text = f"공개 예정: {kst:%Y-%m-%d %H:%M} (한국 시간)"
                    if start <= datetime.now(timezone.utc):
                        schedule_text += "\n예정 시간이 지났지만 아직 시작되지 않았습니다. 일정이 변경되었을 수 있습니다."
                except (ValueError, TypeError):
                    schedule_text = "공개 예정 시간을 확인할 수 없습니다."
            raise YouTubeSummaryUnavailable(
                "아직 공개되지 않은 예약 방송 또는 최초 공개 영상이어서 요약할 수 없습니다.\n" + schedule_text
            )
        upload = status.get("uploadStatus")
        unavailable = {
            "deleted": "삭제된 영상이어서 요약할 수 없습니다.",
            "failed": "업로드에 실패한 영상이어서 요약할 수 없습니다.",
            "rejected": "YouTube에서 업로드가 거부된 영상이어서 요약할 수 없습니다.",
            "uploaded": "YouTube에서 영상을 처리 중이어서 아직 요약할 수 없습니다. 처리가 끝난 후 다시 요청해 주세요.",
        }
        if upload in unavailable:
            raise YouTubeSummaryUnavailable(unavailable[upload])
        if status.get("privacyStatus") == "private":
            raise YouTubeSummaryUnavailable("비공개 영상이어서 요약할 수 없습니다.")
        if live.get("actualEndTime") and item.get("contentDetails", {}).get("duration") in {None, "P0D", "PT0S"}:
            raise YouTubeSummaryUnavailable(
                "방송은 종료되었지만 다시보기가 아직 준비되지 않아 요약할 수 없습니다. 나중에 다시 요청해 주세요."
            )
    except (HttpError, KeyError, TypeError, ValueError) as exc:
        raise YouTubeApiError("유튜브 영상 상태를 조회하지 못했습니다.") from exc


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
