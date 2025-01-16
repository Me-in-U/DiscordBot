# def_youtube_summary.py
import os
import re

import whisper
from moviepy import AudioFileClip
from pytube import YouTube
from pytube.exceptions import VideoUnavailable
from yt_dlp import YoutubeDL

# request_gpt.py 에 정의된 함수들 임포트
# send_to_chatgpt, image_analysis 등을 필요에 맞게 사용 가능
from requests_gpt import send_to_chatgpt

# 유튜브 링크 정규식 (간단 예시)
YOUTUBE_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=)?[\w\-\_]+"
)


def is_youtube_link(text: str) -> bool:
    """
    메시지 텍스트에서 유튜브 링크가 있는지 간단히 판별
    """
    return bool(YOUTUBE_PATTERN.search(text))


def extract_youtube_link(text: str) -> str:
    """
    메시지(텍스트)에서 유튜브 링크를 추출
    """
    match = YOUTUBE_PATTERN.search(text)
    if match:
        return match.group()
    return ""


async def youtube_to_mp3(url: str, output_path: str = "youtube_audio.mp3") -> None:
    """
    유튜브 영상을 다운로드(mp4) 한 뒤, mp3로 변환
    """
    file_name = "youtube.mp4"

    try:
        # yt-dlp를 사용하여 오디오만 다운로드
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": file_name,
            "quiet": True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        audio_clip = AudioFileClip(file_name)
        audio_clip.write_audiofile(output_path)
        audio_clip.close()
        # 파일 쓰기 완료 후 확인

        if os.path.exists(output_path):
            print("MP3 파일이 생성되었습니다.")
        else:
            raise FileNotFoundError(f"{output_path} 파일이 생성되지 않았습니다.")

    except VideoUnavailable:
        print("해당 유튜브 영상을 다운로드할 수 없습니다.")
    except Exception as e:
        print(f"유튜브 다운로드 중 오류가 발생했습니다: {e}")
    finally:
        # 파일 정리
        if os.path.exists(file_name):
            os.remove(file_name)
            print("MP4 파일 삭제.")


async def speech_to_text(audio_path: str) -> str:
    """
    whisper로 mp3 -> 텍스트(STT) 변환
    """
    full_path = os.path.abspath(audio_path)

    # 파일 존재 여부 확인
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"{full_path} 파일을 찾을 수 없습니다.")

    print("경로", full_path)
    model = whisper.load_model("small")
    result = model.transcribe(full_path)
    print("result", result)
    return result["text"]


async def summarize_text_with_gpt(text: str) -> str:
    """
    request_gpt.py의 send_to_chatgpt 함수를 사용하여 요약을 수행
    """
    # GPT에게 보낼 메시지
    messages = [
        {
            "role": "system",
            "content": (
                "당신은 전문 요약가입니다. "
                "다음은 유튜브 내용을 텍스트로 바꾼것입니다. "
                "주요내용에 대해서 요약해주세요. "
                "중요 맥락이 누락되지 않도록 유의하세요."
            ),
        },
        {
            "role": "user",
            "content": text,
        },
    ]

    # request_gpt.py의 send_to_chatgpt 함수 호출
    response_text = send_to_chatgpt(
        messages,
        model="gpt-4o-mini-2024-07-18",  # 필요에 맞게 수정
        temperature=0.3,
    )
    return response_text.strip()


async def process_youtube_link(url: str) -> str:
    """
    1) 유튜브 mp3 다운로드 -> 2) STT -> 3) GPT 요약
    최종 요약 텍스트 반환
    """
    mp3_path = "youtube_audio.mp3"

    try:
        # 1) mp3 다운로드
        print("process_youtube_link 1)")
        await youtube_to_mp3(url, mp3_path)

        print("process_youtube_link 2)")
        # 2) Whisper가 MP3 파일을 찾을 수 있는지 확인
        if not os.path.exists(mp3_path):
            raise FileNotFoundError(f"{mp3_path} 파일을 찾을 수 없습니다.")

        # 3) STT (음성을 텍스트로 변환)
        print("process_youtube_link 3)")
        stt_text = await speech_to_text(mp3_path)
        print(stt_text)

        # 4) GPT 요약
        print("process_youtube_link 4)")
        summary_text = await summarize_text_with_gpt(stt_text)

    finally:
        # mp3 파일 정리
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
            print("MP3 파일 삭제.")
        print("finally")

    return summary_text
