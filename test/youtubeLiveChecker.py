import time
import os

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

API_KEY = GOOGLE_API_KEY
CHANNEL_ID = "UCb5NLtXAsTBrmaZVhyFa-Wg"  # 감시할 채널 ID
POLL_INTERVAL = 60  # 초 단위 조회 간격


def is_channel_live(youtube, channel_id):
    """
    channel_id 채널이 live 상태인지 확인.
    성공 시 live 영상의 videoId를, 아니면 None을 반환.
    """
    try:
        req = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            eventType="live",
            type="video",
            maxResults=1,
        )
        res = req.execute()
        items = res.get("items", [])
        if items:
            return items[0]["id"]["videoId"]
    except HttpError as e:
        print(f"API 에러: {e}")
    return None


def main():
    youtube = build("youtube", "v3", developerKey=API_KEY)
    last_live_id = None

    while True:
        vid = is_channel_live(youtube, CHANNEL_ID)
        if vid and vid != last_live_id:
            print(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 채널이 LIVE 시작! ▶ https://youtu.be/{vid}"
            )
            last_live_id = vid
        elif not vid:
            # 채널이 live 아님
            last_live_id = None
            print(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 채널이 LIVE 상태가 아닙니다."
            )
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
