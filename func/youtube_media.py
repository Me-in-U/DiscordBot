from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path

import aiohttp
from faster_whisper import WhisperModel
from pytube.exceptions import VideoUnavailable
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from func.youtube_links import normalize_youtube_link
from func.youtube_workspace import subtitle_output_template


logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Mode": "navigate",
}


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


def detect_ffmpeg_executable() -> str:
    local = os.path.join(os.getcwd(), "bin", "ffmpeg.exe")
    if os.path.exists(local):
        return local
    return "ffmpeg"


def build_headers_str(headers: dict) -> str:
    return "".join([f"{key}: {value}\r\n" for key, value in headers.items()])


async def fetch_stream_info(page_url: str) -> tuple[str, dict]:
    async with aiohttp.ClientSession(headers=HEADERS, trust_env=False) as session:
        async with session.get(page_url) as resp:
            text = await resp.text()
    match = re.search(r"ytInitialPlayerResponse\s*=\s*(\{[^;]+\});", text)
    if not match:
        raise ValueError("ytInitialPlayerResponse not found")

    data = json.loads(match.group(1))
    adaptive_formats = (data.get("streamingData", {}) or {}).get(
        "adaptiveFormats",
        [],
    )
    audio_formats = [
        item
        for item in adaptive_formats
        if str(item.get("mimeType", "")).startswith("audio/")
    ]
    if not audio_formats:
        raise ValueError("no audio formats")

    best = max(audio_formats, key=lambda item: item.get("averageBitrate", 0))
    return best.get("url"), {
        "title": (data.get("videoDetails", {}) or {}).get("title"),
        "duration": int(
            (data.get("videoDetails", {}) or {}).get("lengthSeconds", 0) or 0
        ),
        "webpage_url": page_url,
        "thumbnail": None,
    }


def download_youtube_subtitles(
    url: str,
    primary_lang: str = "ko",
    fallback_lang: str = "en",
    output_dir: str | os.PathLike[str] | None = None,
) -> str:
    workspace = Path(output_dir) if output_dir is not None else Path.cwd()
    workspace.mkdir(parents=True, exist_ok=True)
    logger.debug("YouTube subtitle workspace: %s", workspace)

    def find_subtitle_file(lang: str, auto: bool = False) -> str:
        for pattern in [f"youtube_subtitles.{lang}.vtt", "youtube_subtitles.vtt"]:
            subtitle_files = sorted(workspace.glob(pattern))
            if subtitle_files:
                return str(subtitle_files[0])
        return ""

    def delete_existing_files(lang: str, auto: bool = False) -> None:
        for pattern in [f"youtube_subtitles.{lang}.vtt", "youtube_subtitles.vtt"]:
            for fp in workspace.glob(pattern):
                try:
                    fp.unlink()
                    logger.debug("기존 자막 파일 삭제: path=%s", fp)
                except OSError:
                    logger.debug("기존 자막 파일 삭제 실패: path=%s", fp, exc_info=True)

    def download_subtitles(lang: str, auto: bool = False) -> str:
        delete_existing_files(lang, auto)

        cookies_path = os.path.join(os.getcwd(), "cookies.txt")
        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": auto,
            "subtitleslangs": [lang],
            "skip_download": True,
            "outtmpl": subtitle_output_template(workspace),
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

            subtitle_file = find_subtitle_file(lang, auto=auto)
            if subtitle_file:
                logger.debug(
                    "%s %s자막 파일 다운로드 성공: path=%s",
                    lang,
                    "자동생성 " if auto else "",
                    subtitle_file,
                )
                return subtitle_file
            logger.debug(
                "%s %s자막 파일이 생성되지 않았습니다.",
                lang,
                "자동생성 " if auto else "",
            )

        except (DownloadError, OSError, ValueError):
            logger.warning(
                "%s %s자막 다운로드 중 오류",
                lang,
                "자동생성 " if auto else "",
                exc_info=True,
            )
        return ""

    subtitles_path = download_subtitles(primary_lang)
    if subtitles_path:
        return subtitles_path

    logger.debug("한글 자막이 없습니다. 자동생성 자막을 시도합니다.")
    subtitles_path = download_subtitles(primary_lang, auto=True)
    if subtitles_path:
        return subtitles_path

    subtitles_path = download_subtitles(fallback_lang, auto=True)
    if subtitles_path:
        return subtitles_path

    logger.debug("사용 가능한 자막이 없습니다.")
    return ""


async def youtube_to_mp3(
    url: str,
    output_path: str | os.PathLike[str] = "youtube_audio.mp3",
) -> None:
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    output_template = str(output_path_obj.with_suffix(""))
    try:

        def _download_with_ytdlp():
            ffmpeg_exec = detect_ffmpeg_executable()
            cookies_path = os.path.join(os.getcwd(), "cookies.txt")
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
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

        if output_path_obj.exists():
            logger.debug("MP3 파일이 생성되었습니다: path=%s", output_path_obj)
        else:
            raise FileNotFoundError(f"{output_path_obj} 파일이 생성되지 않았습니다.")

    except VideoUnavailable:
        logger.warning("해당 유튜브 영상을 다운로드할 수 없습니다: url=%s", url, exc_info=True)
    except (DownloadError, OSError, ValueError):
        logger.warning("yt-dlp 다운로드/변환 실패, ffmpeg 직접 추출 시도: url=%s", url, exc_info=True)
        try:
            page_url = normalize_youtube_link(url)
            audio_url, _ = await fetch_stream_info(page_url)
            if not audio_url:
                raise RuntimeError("오디오 스트림 URL을 찾지 못했습니다.")

            def _run_ffmpeg():
                cmd = [
                    detect_ffmpeg_executable(),
                    "-y",
                    "-hide_banner",
                    "-nostats",
                    "-loglevel",
                    "error",
                    "-headers",
                    build_headers_str(HEADERS),
                    "-i",
                    audio_url,
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    "320k",
                    str(output_path_obj),
                ]
                subprocess.run(cmd, check=True)

            await asyncio.to_thread(_run_ffmpeg)
            if output_path_obj.exists():
                logger.debug("MP3 파일이 생성되었습니다.(ffmpeg): path=%s", output_path_obj)
            else:
                raise FileNotFoundError(f"{output_path_obj} 파일이 생성되지 않았습니다.(ffmpeg)")
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
            ValueError,
        ):
            logger.exception("ffmpeg 직접 추출도 실패: url=%s", url)
            raise


async def speech_to_text(audio_path: str) -> str:
    def _run_stt():
        full_path = os.path.abspath(audio_path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(
                f"STT를 위한 '{full_path}' 파일을 찾을 수 없습니다."
            )

        logger.debug("STT input path: %s", full_path)
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            full_path,
            language="ko",
            condition_on_previous_text=False,
            vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text)
        logger.debug("STT completed: chars=%s", len(text))
        return text

    return await asyncio.to_thread(_run_stt)
