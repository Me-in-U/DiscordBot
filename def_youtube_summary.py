# def_youtube_summary.py
import glob
import os
import re

import whisper
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


def normalize_youtube_link(url: str) -> str:
    """
    유튜브 쇼츠 링크를 일반 유튜브 영상 링크로 변환
    """
    if "youtube.com/shorts/" in url:
        # 쇼츠 링크를 일반 영상 링크로 변환
        url = url.replace("youtube.com/shorts/", "youtube.com/watch?v=")
        print("쇼츠 -> 일반영상 변환환 주소", url)
        return url
    print("일반 영상 주소", url)
    return url


def extract_youtube_link(link: str) -> str:
    """
    메시지(텍스트)에서 유튜브 링크를 추출
    """
    # 쇼츠 링크를 일반 링크로 변환
    link = normalize_youtube_link(link)
    match = YOUTUBE_PATTERN.search(link)
    if match:
        return match.group()
    return ""


def download_youtube_subtitles(
    url: str, primary_lang: str = "ko", fallback_lang: str = "en"
) -> str:
    """
    유튜브 자막 다운로드 (한글 -> 영어 -> 자동생성 자막, 현재 디렉토리에 저장)
    """
    # 현재 디렉토리 출력
    current_directory = os.getcwd()
    print(f"현재 디렉토리: {current_directory}")

    def find_subtitle_file(lang: str, auto: bool = False) -> str:
        """다운로드된 자막 파일 검색"""
        subtitle_files = glob.glob(f"youtube_subtitles.{lang}.vtt")
        if subtitle_files:
            return subtitle_files[0]
        return ""

    def delete_existing_files(lang: str, auto: bool = False) -> None:
        """기존 자막 파일 삭제"""
        subtitle_file = find_subtitle_file(lang, auto)
        if subtitle_file and os.path.exists(subtitle_file):
            os.remove(subtitle_file)
            print(f"기존 파일 삭제: {subtitle_file}")

    def download_subtitles(lang: str, auto: bool = False) -> str:
        """지정된 언어로 자막 다운로드"""
        # 기존 파일 삭제
        delete_existing_files(lang, auto)

        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": auto,  # 자동생성 자막 다운로드
            "subtitleslangs": [lang],
            "skip_download": True,
            "outtmpl": f"youtube_subtitles.%(ext)s",  # 현재 디렉토리 지정
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # 다운로드된 자막 파일 검색
            subtitle_file = find_subtitle_file(lang, auto=auto)
            if subtitle_file:
                print(
                    f"{lang} {'자동생성 ' if auto else ''}자막 파일 다운로드 성공: {subtitle_file}"
                )
                return subtitle_file
            else:
                print(
                    f"{lang} {'자동생성 ' if auto else ''}자막 파일이 생성되지 않았습니다."
                )

        except Exception as e:
            print(
                f"{lang} {'자동생성 ' if auto else ''}자막 다운로드 중 오류가 발생했습니다: {e}"
            )
        return ""

    # 한글 자막 우선 다운로드 시도
    subtitles_path = download_subtitles(primary_lang)
    if subtitles_path:
        return subtitles_path

    # 한글/영어 자막이 없으면 자동생성 자막 다운로드 시도
    print("한글 자막이 없습니다. 자동생성 자막을 시도합니다.")
    subtitles_path = download_subtitles(primary_lang, auto=True)
    if subtitles_path:
        return subtitles_path

    subtitles_path = download_subtitles(fallback_lang, auto=True)
    if subtitles_path:
        return subtitles_path

    print("사용 가능한 자막이 없습니다.")
    return ""


def read_subtitles_file(file_path: str) -> str:
    """
    VTT 자막 파일을 텍스트로 변환
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # VTT 파일에서 타임스탬프와 메타데이터를 제외한 텍스트만 추출
        text = "\n".join(
            line.strip()
            for line in lines
            if line.strip() and not re.match(r"\d{2}:\d{2}:\d{2}\.\d{3}", line)
        )
        return text
    except Exception as e:
        print(f"자막 파일 읽기 중 오류가 발생했습니다: {e}")
        return ""


async def youtube_to_mp3(url: str, output_path: str = "youtube_audio") -> None:
    """
    유튜브 영상을 다운로드(mp4) 한 뒤, mp3로 변환
    """
    try:
        # yt-dlp를 사용하여 오디오만 다운로드
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": "youtube_audio",
            "postprocessors": [
                {  # Post-process to convert to MP3
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",  # Convert to mp3
                    "preferredquality": "320",  # '0' means best quality, auto-determined by source
                }
            ],
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # 파일 쓰기 완료 후 확인
        if os.path.exists("youtube_audio.mp3"):
            print("MP3 파일이 생성되었습니다.")
        else:
            raise FileNotFoundError("youtube_audio.mp3 파일이 생성되지 않았습니다.")

    except VideoUnavailable:
        print("해당 유튜브 영상을 다운로드할 수 없습니다.")
    except Exception as e:
        print(f"유튜브 다운로드 중 오류가 발생했습니다: {e}")


async def speech_to_text(audio_path: str) -> str:
    """
    whisper로 mp3 -> 텍스트(STT) 변환
    """
    full_path = os.path.abspath(audio_path)

    # 파일 존재 여부 확인
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"{full_path} 파일을 찾을 수 없습니다.")

    print("경로", full_path)
    model = whisper.load_model("tiny").to("cpu")
    result = model.transcribe(full_path)
    # print("result", result)
    print("result:text -> \n", result["text"])
    return result["text"]


async def summarize_text_with_gpt(text: str) -> str:
    """
    request_gpt.py의 send_to_chatgpt 함수를 사용하여 요약을 수행
    """
    # GPT에게 보낼 메시지
    messages = [
        {
            "role": "developer",
            "content": (
                "당신은 전문 요약가입니다. "
                "다음은 유튜브 내용을 텍스트로 바꾼것입니다. "
                "주요내용에 대해서 요약해주세요. "
                "중요 맥락이 누락되지 않도록 유의하세요. "
                "내용을 간단한 문장으로 3줄 요약하세요. 1.~ 2.~ 3.~"
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
    1) 자막 다운로드 (한글 -> 영어) -> 2) (자막 없으면) MP3/STT -> 3) GPT 요약
    """
    mp3_path = "youtube_audio.mp3"
    try:
        # 1) 자막 다운로드 시도 (한글 -> 영어)
        subtitle_path = download_youtube_subtitles(
            url, primary_lang="ko", fallback_lang="en"
        )

        if subtitle_path:
            print("자막이 확인되었습니다. 자막을 사용합니다.")
            # 자막 파일 내용을 읽어 텍스트로 변환
            subtitles_text = read_subtitles_file(subtitle_path)
            if not subtitles_text.strip():
                print("자막 파일이 비어 있습니다. STT로 진행합니다.")
                raise ValueError("자막 파일이 비어 있습니다.")
            # GPT 요약 요청
            summary_text = await summarize_text_with_gpt(subtitles_text)
        else:
            print("자막이 없습니다. STT를 진행합니다.")
            # 오디오 다운로드 및 STT 처리
            await youtube_to_mp3(url)

            if not os.path.exists(mp3_path):
                raise FileNotFoundError(f"{mp3_path} 파일을 찾을 수 없습니다.")

            stt_text = await speech_to_text(mp3_path)
            summary_text = await summarize_text_with_gpt(stt_text)

    finally:
        # MP3 파일 정리
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
            print("MP3 파일 삭제 완료.")

    return summary_text
