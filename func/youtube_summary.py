# def_youtube_summary.py
import asyncio
import glob
import os
import re

import discord
import whisper
from dotenv import load_dotenv
from googleapiclient.discovery import build
from pytube.exceptions import VideoUnavailable
from yt_dlp import YoutubeDL

# request_gpt.py 에 정의된 함수들 임포트
# send_to_chatgpt, image_analysis 등을 필요에 맞게 사용 가능
from api.chatGPT import general_purpose_model

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise EnvironmentError("GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다.")
# 유튜브 링크 정규식 (간단 예시)
YOUTUBE_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|live/)?[\w\-\_]+"
)


# --- 영상 ID 추출 함수 추가 ---
def extract_video_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|live/)([\w\-]+)", url)
    if match:
        return match.group(1)
    return ""


# --- 라이브 영상 여부 확인 함수 추가 ---
def is_live_video(video_id: str) -> bool:
    """
    YouTube Data API를 사용해 영상이 라이브 또는 예정인지 확인합니다.
    liveBroadcastContent 값이 "live" 또는 "upcoming"이면 True를 반환합니다.
    """
    youtube = build("youtube", "v3", developerKey=GOOGLE_API_KEY)
    response = youtube.videos().list(part="snippet", id=video_id).execute()

    items = response.get("items", [])
    if not items:
        return False  # 정보가 없으면 False 처리

    live_broadcast_content = items[0]["snippet"].get("liveBroadcastContent", "none")
    return live_broadcast_content in ["live", "upcoming"]


# --- YouTube Data API를 활용하여 댓글을 가져오는 함수 추가 ---
def fetch_youtube_comments(video_id: str, max_comments: int = 10) -> list:
    """
    주어진 영상 ID에 대해 최대 max_comments 개의 댓글을 가져옵니다.
    """

    api_key = GOOGLE_API_KEY
    youtube = build("youtube", "v3", developerKey=api_key)
    comments = []
    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_comments,
            textFormat="plainText",
        )
        response = request.execute()
        for item in response.get("items", []):
            comment = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(comment)
    except Exception as e:
        print(f"댓글 가져오기 오류: {e}")
    return comments


# --- 댓글 요약을 위한 함수 추가 ---
async def summarize_comments_with_gpt(comments: list) -> str:
    """
    가져온 댓글들을 1줄로 요약합니다.
    """
    comments_text = "\n".join(comments)
    messages = [
        {
            "role": "developer",
            "content": (
                "당신은 전문 요약가입니다. "
                "다음은 유튜브 영상의 댓글입니다. "
                "주요 내용을 70자 이내로 압축 요약해주세요."
            ),
        },
        {
            "role": "user",
            "content": comments_text,
        },
    ]
    response_text = general_purpose_model(
        messages,
        model="gpt-4o-mini",
        temperature=0.4,
    )
    return response_text


# --- Discord UI: 요약 진행 여부 확인용 View ---
class YouTubeSummaryView(discord.ui.View):
    def __init__(self, youtube_url: str):
        super().__init__(timeout=300)
        self.youtube_url = youtube_url
        self.original_message: discord.Message = None  # 나중에 할당됨

    @discord.ui.button(label="요약하기", style=discord.ButtonStyle.primary)
    async def yes_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # 1) 상호작용 실패 방지를 위해 즉시 defer (ephemeral=True면 "개인 메시지"로 처리)
        await interaction.response.defer(ephemeral=True, thinking=False)

        # 2) 버튼 상태를 "진행 중"으로 갱신 → 원본 메시지 수정
        button.disabled = True
        button.label = "요약 진행중"
        button.style = discord.ButtonStyle.success
        await self.original_message.edit(view=self)

        try:
            # 3) 오래 걸리는 작업 수행 (다운로드, STT, GPT 요약 등)
            summary_result = await process_youtube_link(self.youtube_url)

            # 4) 원본 메시지를 최종 결과로 교체
            await self.original_message.edit(
                content=f"**[영상 3줄 요약]**\n{summary_result}", view=None  # 버튼 제거
            )

        except Exception as e:
            # 에러 시 메시지 갱신
            button.disabled = True
            button.label = "오류!"
            button.style = discord.ButtonStyle.danger
            await self.original_message.edit(
                content=f"오류가 발생했습니다: {e}", view=self
            )

        self.stop()

    async def on_timeout(self):
        # 시간이 초과되면 버튼을 비활성화
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                child.label = "기간만료!"
                child.style = discord.ButtonStyle.danger
        if self.original_message:
            # 만료 표시로 메시지를 갱신
            await self.original_message.edit(content="5분이내만 가능", view=self)

            # 1분 대기 후 메시지 삭제
            await asyncio.sleep(60)
            try:
                await self.original_message.delete()
            except discord.NotFound:
                # 이미 다른 곳에서 삭제되었을 수도 있으므로 무시
                pass


async def check_youtube_link(message):
    if is_youtube_link(message.content):
        youtube_url = extract_youtube_link(message.content)
        if youtube_url:
            view = YouTubeSummaryView(youtube_url)
            # "유튜브 영상 요약을 진행하시겠습니까?" 메시지를 채널에 1개만 보냄
            sent_msg = await message.reply(
                content="유튜브 영상 요약을 진행하시겠습니까?", view=view
            )
            # View 내부에서 원본 메시지를 수정하기 위해 메시지 객체를 저장
            view.original_message = sent_msg


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
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        clean_lines = []
        seen = set()

        for line in lines:
            # 양쪽 공백 제거
            line = line.strip()
            # WEBVTT 헤더 및 타임스탬프 라인은 건너뜁니다.
            if line.startswith("WEBVTT") or re.match(r"\d{2}:\d{2}:\d{2}\.\d{3}", line):
                continue

            # 내부에 포함된 타임코드 태그(<00:00:00.799> 등) 제거
            line = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", line)
            # <c> 태그 제거
            line = re.sub(r"</?c>", "", line)
            # 만약 같은 내용이 이미 추가되었다면 스킵
            if line and line not in seen:
                clean_lines.append(line)
                seen.add(line)

        clean_text = remove_unnecessary_line_breaks("\n".join(clean_lines))
        return clean_text
    except Exception as e:
        print(f"자막 파일 읽기 중 오류가 발생했습니다: {e}")
        return ""


def remove_unnecessary_line_breaks(text: str) -> str:
    # 모든 줄바꿈을 공백으로 변환합니다.
    text = re.sub(r"\n+", " ", text)
    # 문장 종결 부호 뒤에 줄바꿈을 추가합니다.
    # 이 예시는 한국어 문장에서 "다", "요", "습니다" 뒤에 줄바꿈을 넣습니다.
    text = re.sub(r"([다요습니다])\s+", r"\1\n", text)
    # 양쪽 공백 제거 후 반환
    return text.strip()


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
        raise FileNotFoundError(
            f"whisper로 stt를 위한 '{full_path}' 파일을 찾을 수 없습니다."
        )

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
                "주요 내용에 대해서 요약해주세요. "
                "중요 대화 맥락이 누락되지 않도록 유의하세요. "
                "내용을 50자 이내로 3줄 압축 요약하세요. 1. 2. 3."
            ),
        },
        {
            "role": "user",
            "content": text,
        },
    ]

    # request_gpt.py의 send_to_chatgpt 함수 호출
    response_text = general_purpose_model(
        messages,
        model="gpt-4o-mini",  # 필요에 맞게 수정
        temperature=0.4,
    )
    return response_text


async def process_youtube_link(url: str) -> str:
    """
    1) 자막 다운로드 (한글 -> 영어) -> 2) (자막 없으면) MP3/STT -> 3) GPT 요약
    """
    mp3_path = "youtube_audio.mp3"
    summary_text = ""
    try:
        video_id = extract_video_id(url)
        if not video_id:
            raise ValueError("영상 ID를 추출하지 못했습니다.")

        # 라이브 영상이면 요약 진행하지 않음
        if is_live_video(video_id):
            raise ValueError("라이브(또는 예정) 방송은 요약을 진행할 수 없습니다.")

        # ! 자막 다운로드 시도 (한글 -> 영어)
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
            stt_text = await speech_to_text(mp3_path)
            summary_text = await summarize_text_with_gpt(stt_text)

        # !댓글 가져오기 및 요약 추가
        video_id = extract_video_id(url)
        if video_id:
            comments = fetch_youtube_comments(video_id, max_comments=40)
            if comments:
                comments_summary = await summarize_comments_with_gpt(comments)
                summary_text += "\n\n**[댓글 요약]**\n" + comments_summary
            else:
                print("댓글을 가져오지 못했습니다.")
        else:
            print("영상 ID를 추출하지 못했습니다.")

    finally:
        # MP3 파일 정리
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
            print("MP3 파일 삭제 완료.")

    return summary_text.strip()
