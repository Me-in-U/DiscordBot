# def_youtube_summary.py
import os
import re
import whisper
from pytube import YouTube
from moviepy.editor import AudioFileClip

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
    pytube로 유튜브 영상을 다운로드(mp4) 한 뒤, moviepy로 mp3로 변환
    """
    yt = YouTube(url)
    # 오디오 스트림만 필터링
    stream = yt.streams.filter(only_audio=True).first()
    downloaded_file = stream.download()  # mp4 파일 다운로드

    # moviepy를 사용해 mp4 -> mp3 변환
    audio_clip = AudioFileClip(downloaded_file)
    audio_clip.write_audiofile(output_path)
    audio_clip.close()

    # 임시 mp4 파일은 제거
    if os.path.exists(downloaded_file):
        os.remove(downloaded_file)


async def speech_to_text(audio_path: str) -> str:
    """
    whisper로 mp3 -> 텍스트(STT) 변환
    """
    model = whisper.load_model(
        "small"
    )  # 모델 크기(base, small, medium, large 등 상황에 맞게)
    result = model.transcribe(audio_path)
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
                "다음 텍스트의 주요 내용을 5~6줄 이내로 간결하게 요약하세요. "
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
        await youtube_to_mp3(url, mp3_path)

        # 2) STT (음성을 텍스트로 변환)
        stt_text = await speech_to_text(mp3_path)

        # 3) GPT 요약
        summary_text = await summarize_text_with_gpt(stt_text)

    finally:
        # mp3 파일 정리 (에러 발생 여부와 무관하게 수행)
        if os.path.exists(mp3_path):
            os.remove(mp3_path)

    return summary_text
