# def_youtube_summary.py
import asyncio
import glob
import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse, urlunparse

import aiohttp
import discord
import subprocess
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from googleapiclient.discovery import build
from pytube.exceptions import VideoUnavailable
from yt_dlp import YoutubeDL
from util.env_utils import getenv_clean, sanitize_environment


# request_gpt.py 에 정의된 함수들 임포트
from api.chatGPT import custom_prompt_model, generate_text_model

load_dotenv()
sanitize_environment()
GOOGLE_API_KEY = getenv_clean("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise EnvironmentError("GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다.")

YOUTUBE_URL_PATTERN = re.compile(
    r"(?P<url>(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s<>()\[\]{}]+)"
)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
YOUTUBE_POST_KIND = "post"
YOUTUBE_VIDEO_KIND = "video"

# 공통 HTTP 헤더 (YouTube 우회에 도움)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Mode": "navigate",
}


# yt-dlp 무음 로거
class _SilentYTDLLogger:
    def debug(self, msg):
        return

    def info(self, msg):
        return

    def warning(self, msg):
        return

    def error(self, msg):
        return


YTDL_LOGGER = _SilentYTDLLogger()


@dataclass(slots=True)
class YouTubePostInfo:
    post_id: str
    url: str
    author: str = ""
    published_time: str = ""
    like_count: str = ""
    text: str = ""
    attachment_urls: list[str] = field(default_factory=list)


def _detect_ffmpeg_executable() -> str:
    """bin/ffmpeg.exe가 있으면 우선 사용, 없으면 시스템 PATH의 ffmpeg 사용"""
    local = os.path.join(os.getcwd(), "bin", "ffmpeg.exe")
    if os.path.exists(local):
        return local
    return "ffmpeg"


def _build_headers_str(headers: dict) -> str:
    return "".join([f"{k}: {v}\r\n" for k, v in headers.items()])


async def _fetch_stream_info(page_url: str) -> tuple[str, dict]:
    """YouTube 페이지에서 ytInitialPlayerResponse를 파싱해 최고 비트레이트 오디오 URL을 얻는다."""
    async with aiohttp.ClientSession(headers=HEADERS, trust_env=False) as session:
        async with session.get(page_url) as resp:
            text = await resp.text()
    m = re.search(r"ytInitialPlayerResponse\s*=\s*(\{[^;]+\});", text)
    if not m:
        raise ValueError("ytInitialPlayerResponse not found")
    data = __import__("json").loads(m.group(1))
    af = (data.get("streamingData", {}) or {}).get("adaptiveFormats", [])
    audio_formats = [f for f in af if str(f.get("mimeType", "")).startswith("audio/")]
    if not audio_formats:
        raise ValueError("no audio formats")
    best = max(audio_formats, key=lambda f: f.get("averageBitrate", 0))
    return best.get("url"), {
        "title": (data.get("videoDetails", {}) or {}).get("title"),
        "duration": int(
            (data.get("videoDetails", {}) or {}).get("lengthSeconds", 0) or 0
        ),
        "webpage_url": page_url,
        "thumbnail": None,
    }


def _strip_wrapping_punctuation(url: str) -> str:
    return url.strip().lstrip("<(").rstrip(">.,!?)]}\"'")


def _ensure_https_scheme(url: str) -> str:
    if re.match(r"^http://", url, flags=re.IGNORECASE):
        return re.sub(r"^http://", "https://", url, count=1, flags=re.IGNORECASE)
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        return f"https://{url}"
    return url


def _normalize_thumbnail_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _get_text_from_runs(data: dict | None) -> str:
    if not isinstance(data, dict):
        return ""
    simple_text = data.get("simpleText")
    if isinstance(simple_text, str):
        return simple_text.strip()

    parts = []
    for run in data.get("runs", []):
        text = run.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts).strip()


def _get_vote_count_text(vote_count: dict | None) -> str:
    text = _get_text_from_runs(vote_count)
    if text:
        return text

    accessibility = (vote_count or {}).get("accessibility", {})
    accessibility_data = accessibility.get("accessibilityData", {})
    return str(accessibility_data.get("label", "")).strip()


def _find_first_key_value(data, target_key: str):
    stack = [data]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if target_key in current:
                return current[target_key]
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return None


def _extract_json_object_after(text: str, marker: str) -> dict:
    marker_index = text.find(marker)
    if marker_index == -1:
        raise ValueError(f"{marker} marker not found")

    start_index = text.find("{", marker_index)
    if start_index == -1:
        raise ValueError(f"{marker} JSON start not found")

    depth = 0
    in_string = False
    escaped = False

    for index in range(start_index, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start_index : index + 1])

    raise ValueError(f"{marker} JSON end not found")


def _best_thumbnail_url(thumbnails: list[dict]) -> str:
    valid_thumbnails = [thumb for thumb in thumbnails if thumb.get("url")]
    if not valid_thumbnails:
        return ""

    best = max(
        valid_thumbnails,
        key=lambda thumb: thumb.get("width", 0) * thumb.get("height", 0),
    )
    return _normalize_thumbnail_url(best["url"])


def _collect_attachment_urls(attachment) -> list[str]:
    if not attachment:
        return []

    urls = []
    seen = set()
    stack = [attachment]

    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            thumbnails = current.get("thumbnails")
            if isinstance(thumbnails, list):
                thumbnail_url = _best_thumbnail_url(thumbnails)
                if thumbnail_url and thumbnail_url not in seen:
                    seen.add(thumbnail_url)
                    urls.append(thumbnail_url)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)

    return urls


def parse_youtube_post_html(html: str, url: str) -> YouTubePostInfo:
    initial_data = _extract_json_object_after(html, "var ytInitialData = ")
    post_data = _find_first_key_value(initial_data, "backstagePostRenderer")
    if not isinstance(post_data, dict):
        raise ValueError("유튜브 게시물 정보를 찾지 못했습니다.")

    return YouTubePostInfo(
        post_id=post_data.get("postId") or extract_post_id(url),
        url=url,
        author=_get_text_from_runs(post_data.get("authorText")),
        published_time=_get_text_from_runs(post_data.get("publishedTimeText")),
        like_count=_get_vote_count_text(post_data.get("voteCount")),
        text=_get_text_from_runs(post_data.get("contentText")),
        attachment_urls=_collect_attachment_urls(post_data.get("backstageAttachment")),
    )


def get_youtube_link_kind(url: str) -> str | None:
    normalized_url = _ensure_https_scheme(_strip_wrapping_punctuation(url))
    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()

    if host not in YOUTUBE_HOSTS:
        return None

    path = parsed.path or ""
    if host == "youtu.be":
        return YOUTUBE_VIDEO_KIND if path.strip("/") else None

    if path.startswith("/post/"):
        return YOUTUBE_POST_KIND

    if path == "/watch" and parse_qs(parsed.query).get("v"):
        return YOUTUBE_VIDEO_KIND

    if path.startswith("/live/") or path.startswith("/shorts/"):
        return YOUTUBE_VIDEO_KIND

    return None


def get_youtube_prompt_text(link_kind: str) -> str:
    if link_kind == YOUTUBE_POST_KIND:
        return "유튜브 게시물 요약을 진행하시겠습니까?"
    return "유튜브 영상 요약을 진행하시겠습니까?"


def get_youtube_summary_title(link_kind: str) -> str:
    if link_kind == YOUTUBE_POST_KIND:
        return "**[게시물 요약]**"
    return "**[영상 3줄 요약]**"


def find_latest_youtube_link_in_messages(messages) -> tuple[str, str] | None:
    for message in messages:
        content = getattr(message, "content", "") or ""
        youtube_url = extract_youtube_link(content)
        if youtube_url:
            link_kind = get_youtube_link_kind(youtube_url) or YOUTUBE_VIDEO_KIND
            return youtube_url, link_kind
    return None


async def find_latest_youtube_link_in_channel(
    channel, limit: int = 100
) -> tuple[str, str] | None:
    history = getattr(channel, "history", None)
    if history is None:
        return None

    messages = [message async for message in channel.history(limit=limit)]
    return find_latest_youtube_link_in_messages(messages)


def extract_video_id(url: str) -> str:
    normalized_url = normalize_youtube_link(url)
    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()
    path = parsed.path or ""

    if host == "youtu.be":
        return path.strip("/").split("/", 1)[0]

    if path == "/watch":
        return parse_qs(parsed.query).get("v", [""])[0]

    if path.startswith("/live/"):
        return path.split("/live/", 1)[1].split("/", 1)[0]

    if path.startswith("/shorts/"):
        return path.split("/shorts/", 1)[1].split("/", 1)[0]

    return ""


def extract_post_id(url: str) -> str:
    normalized_url = _ensure_https_scheme(_strip_wrapping_punctuation(url))
    parsed = urlparse(normalized_url)
    path = parsed.path or ""
    if path.startswith("/post/"):
        return path.split("/post/", 1)[1].split("/", 1)[0]
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
    response_text = await asyncio.to_thread(
        custom_prompt_model,
        prompt={
            "id": "pmpt_68abfada6cc8819392effc146b3a39730a3a8fd787c57011",
            "version": "8",
            "variables": {"comments_text": comments_text},
        },
    )
    return response_text


# --- Discord UI: 요약 진행 여부 확인용 View ---
class YouTubeSummaryView(discord.ui.View):
    def __init__(self, youtube_url: str, link_kind: str):
        super().__init__(timeout=300)
        self.youtube_url = youtube_url
        self.link_kind = link_kind
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
                content=f"{get_youtube_summary_title(self.link_kind)}\n{summary_result}",
                view=None,
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
    youtube_url = extract_youtube_link(message.content)
    if youtube_url:
        link_kind = get_youtube_link_kind(youtube_url) or YOUTUBE_VIDEO_KIND
        view = YouTubeSummaryView(youtube_url, link_kind)
        sent_msg = await message.reply(
            content=get_youtube_prompt_text(link_kind), view=view
        )
        view.original_message = sent_msg


def is_youtube_link(text: str) -> bool:
    """
    메시지 텍스트에서 유튜브 링크가 있는지 간단히 판별
    """
    return bool(extract_youtube_link(text))


def normalize_youtube_link(url: str) -> str:
    """
    유튜브 쇼츠 링크를 일반 유튜브 영상 링크로 변환
    """
    cleaned_url = _ensure_https_scheme(_strip_wrapping_punctuation(url))
    parsed = urlparse(cleaned_url)
    path = parsed.path or ""

    if path.startswith("/shorts/"):
        video_id = path.split("/shorts/", 1)[1].split("/", 1)[0]
        normalized = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                "/watch",
                "",
                f"v={video_id}",
                "",
            )
        )
        print("쇼츠 -> 일반영상 변환 주소", normalized)
        return normalized

    print("일반 유튜브 주소", cleaned_url)
    return cleaned_url


def extract_youtube_link(link: str) -> str:
    """
    메시지(텍스트)에서 유튜브 링크를 추출
    """
    for match in YOUTUBE_URL_PATTERN.finditer(link):
        candidate_url = normalize_youtube_link(match.group("url"))
        if get_youtube_link_kind(candidate_url):
            return candidate_url
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
        # 일반: youtube_subtitles.ko.vtt
        for pattern in [f"youtube_subtitles.{lang}.vtt", "youtube_subtitles.vtt"]:
            subtitle_files = glob.glob(pattern)
            if subtitle_files:
                return subtitle_files[0]
        return ""

    def delete_existing_files(lang: str, auto: bool = False) -> None:
        """기존 자막 파일 삭제"""
        for pattern in [f"youtube_subtitles.{lang}.vtt", "youtube_subtitles.vtt"]:
            for fp in glob.glob(pattern):
                try:
                    os.remove(fp)
                    print(f"기존 파일 삭제: {fp}")
                except Exception:
                    pass

    def download_subtitles(lang: str, auto: bool = False) -> str:
        """지정된 언어로 자막 다운로드"""
        # 기존 파일 삭제
        delete_existing_files(lang, auto)

        # cookies.txt가 있으면 사용
        cookies_path = os.path.join(os.getcwd(), "cookies.txt")
        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": auto,  # 자동생성 자막 다운로드
            "subtitleslangs": [lang],
            "skip_download": True,
            "outtmpl": "youtube_subtitles.%(ext)s",  # 베이스명 유지
            "noplaylist": True,
            "no_warnings": True,
            "quiet": True,
            "logger": YTDL_LOGGER,
            "http_headers": HEADERS,
            "extractor_retries": 2,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "source_address": "0.0.0.0",
        }
        if os.path.exists(cookies_path):
            ydl_opts["cookiefile"] = cookies_path

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
            print(f"{lang} {'자동생성 ' if auto else ''}자막 다운로드 중 오류: {e}")
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


async def youtube_to_mp3(url: str) -> None:
    """
    유튜브 영상을 다운로드(mp4) 한 뒤, mp3로 변환
    """
    try:
        def _download_with_ytdlp():
            ffmpeg_exec = _detect_ffmpeg_executable()
            # yt-dlp를 사용하여 오디오만 다운로드 후 mp3로 변환
            cookies_path = os.path.join(os.getcwd(), "cookies.txt")
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": "youtube_audio",  # 베이스 파일명
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "320",
                    }
                ],
                "ffmpeg_location": (
                    os.path.dirname(ffmpeg_exec) if ffmpeg_exec != "ffmpeg" else None
                ),
                "http_headers": HEADERS,
                "noplaylist": True,
                "no_warnings": True,
                "quiet": True,
                "logger": YTDL_LOGGER,
                "extractor_retries": 2,
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
                "source_address": "0.0.0.0",
            }
            if os.path.exists(cookies_path):
                ydl_opts["cookiefile"] = cookies_path
            with YoutubeDL({k: v for k, v in ydl_opts.items() if v is not None}) as ydl:
                ydl.download([url])

        await asyncio.to_thread(_download_with_ytdlp)

        # 파일 쓰기 완료 후 확인
        if os.path.exists("youtube_audio.mp3"):
            print("MP3 파일이 생성되었습니다.")
        else:
            raise FileNotFoundError("youtube_audio.mp3 파일이 생성되지 않았습니다.")

    except VideoUnavailable:
        print("해당 유튜브 영상을 다운로드할 수 없습니다.")
    except Exception as e:
        print(f"yt-dlp 다운로드/변환 실패, ffmpeg 직접 추출 시도: {e}")
        try:
            # HTML 파싱으로 오디오 스트림 URL 얻기
            page_url = normalize_youtube_link(url)
            audio_url, _ = await _fetch_stream_info(page_url)
            if not audio_url:
                raise RuntimeError("오디오 스트림 URL을 찾지 못했습니다.")
            # ffmpeg로 직접 mp3 변환
            def _run_ffmpeg():
                header_str = _build_headers_str(HEADERS)
                cmd = [
                    _detect_ffmpeg_executable(),
                    "-y",
                    "-hide_banner",
                    "-nostats",
                    "-loglevel",
                    "error",
                    "-headers",
                    header_str,
                    "-i",
                    audio_url,
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    "320k",
                    "youtube_audio.mp3",
                ]
                subprocess.run(cmd, check=True)

            await asyncio.to_thread(_run_ffmpeg)
            if os.path.exists("youtube_audio.mp3"):
                print("MP3 파일이 생성되었습니다.(ffmpeg)")
            else:
                raise FileNotFoundError(
                    "youtube_audio.mp3 파일이 생성되지 않았습니다.(ffmpeg)"
                )
        except Exception as e2:
            print(f"ffmpeg 직접 추출도 실패: {e2}")
            raise


async def speech_to_text(audio_path: str) -> str:
    """
    faster-whisper로 mp3 -> 텍스트(STT) 변환
    """

    def _run_stt():
        full_path = os.path.abspath(audio_path)

        # 파일 존재 여부 확인
        if not os.path.exists(full_path):
            raise FileNotFoundError(
                f"STT를 위한 '{full_path}' 파일을 찾을 수 없습니다."
            )

        print("경로", full_path)
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            full_path,
            language="ko",
            condition_on_previous_text=False,
            vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text)
        print("result:text -> \n", text)
        return text

    return await asyncio.to_thread(_run_stt)


async def summarize_text_with_gpt(youtube_text: str) -> str:
    response_text = await asyncio.to_thread(
        custom_prompt_model,
        prompt={
            "id": "pmpt_68ac079c0d1081958393a758f0b6f4cc01c6576daa0b0eb7",
            "version": "4",
            "variables": {"youtube_text": youtube_text},
        },
    )
    return response_text


def build_youtube_post_summary_input(post_info: YouTubePostInfo) -> str:
    lines = [
        f"게시물 링크: {post_info.url}",
        f"작성자: {post_info.author or '알 수 없음'}",
        f"게시 시각: {post_info.published_time or '알 수 없음'}",
        f"좋아요: {post_info.like_count or '알 수 없음'}",
        "",
        "[본문]",
        post_info.text or "(본문 없음)",
    ]

    if post_info.attachment_urls:
        lines.extend(
            [
                "",
                f"[첨부 이미지 수] {len(post_info.attachment_urls)}",
                *post_info.attachment_urls[:4],
            ]
        )

    return "\n".join(lines).strip()


async def fetch_youtube_post(url: str) -> YouTubePostInfo:
    normalized_url = normalize_youtube_link(url)
    async with aiohttp.ClientSession(headers=HEADERS, trust_env=False) as session:
        async with session.get(normalized_url) as response:
            response.raise_for_status()
            html = await response.text()

    return await asyncio.to_thread(parse_youtube_post_html, html, normalized_url)


async def summarize_youtube_post_with_gpt(post_info: YouTubePostInfo) -> str:
    instructions = (
        "당신은 유튜브 커뮤니티 게시물을 한국어로 요약하는 도우미다. "
        "중요 사실만 추려서 `- ` 로 시작하는 불릿 3개로만 답하고, "
        "원문에 없는 추측이나 과장을 하지 마라."
    )
    post_input = build_youtube_post_summary_input(post_info)
    return await asyncio.to_thread(
        generate_text_model,
        post_input,
        instructions,
        "gpt-5-mini",
        400,
    )


async def process_youtube_post_link(url: str) -> str:
    post_info = await fetch_youtube_post(url)
    if not post_info.text and not post_info.attachment_urls:
        raise ValueError("게시물 본문을 추출하지 못했습니다.")

    return await summarize_youtube_post_with_gpt(post_info)


async def process_youtube_video_link(url: str) -> str:
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
        if await asyncio.to_thread(is_live_video, video_id):
            raise ValueError("라이브(또는 예정) 방송은 요약을 진행할 수 없습니다.")

        # ! 자막 다운로드 시도 (한글 -> 영어)
        subtitle_path = await asyncio.to_thread(
            download_youtube_subtitles, url, primary_lang="ko", fallback_lang="en"
        )

        if subtitle_path:
            print("자막이 확인되었습니다. 자막을 사용합니다.")
            # 자막 파일 내용을 읽어 텍스트로 변환
            subtitles_text = await asyncio.to_thread(
                read_subtitles_file, subtitle_path
            )
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
            comments = await asyncio.to_thread(
                fetch_youtube_comments, video_id, max_comments=40
            )
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


async def process_youtube_link(url: str) -> str:
    link_kind = get_youtube_link_kind(url)
    if link_kind == YOUTUBE_POST_KIND:
        return await process_youtube_post_link(url)
    return await process_youtube_video_link(url)
