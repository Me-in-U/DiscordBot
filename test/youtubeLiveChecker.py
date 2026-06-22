import os
import sys

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from util.youtube.websub import (
    build_youtube_feed_topic_url,
    classify_video_item,
)

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

API_KEY = GOOGLE_API_KEY
YT_CHANNEL_ID = "UCb5NLtXAsTBrmaZVhyFa-Wg"  # 감시할 채널 ID


def get_video_status(youtube, video_id):
    try:
        req = youtube.videos().list(
            part="snippet,liveStreamingDetails,status",
            id=video_id,
            maxResults=1,
        )
        res = req.execute()
        items = res.get("items", [])
        if items:
            return classify_video_item(items[0])
    except HttpError as e:
        print(f"API 에러: {e}")
    return None


def main():
    video_id = sys.argv[1] if len(sys.argv) > 1 else os.getenv("YOUTUBE_LIVE_TEST_VIDEO_ID")
    if not video_id:
        print("WebSub topic:")
        print(build_youtube_feed_topic_url(YT_CHANNEL_ID))
        print("영상 확인: python test/youtubeLiveChecker.py <VIDEO_ID>")
        return

    youtube = build("youtube", "v3", developerKey=API_KEY)
    status = get_video_status(youtube, video_id)
    if status is None:
        print("영상을 찾지 못했습니다.")
        return

    print(f"video_id={status.video_id}")
    print(f"title={status.title}")
    print(f"status={status.status}")
    print(f"scheduled_start_time={status.scheduled_start_time}")


if __name__ == "__main__":
    main()
