from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Literal

import aiohttp
import discord
import yt_dlp as youtube_dl

from util.music.extractor import (
    resolve_search_result_url,
    select_best_audio_format,
    select_yt_dlp_entry,
)
from util.music_stream import (
    build_stream_info_from_player_response,
    extract_initial_player_response,
    select_initial_audio_format,
)


logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-threads 2 -vn -ac 2 -ar 48000 -acodec libopus -compression_level 5 -application audio -hide_banner -nostats -loglevel error",
}

YTDL_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ytdl")


def dbg(msg: str) -> None:
    try:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[MUSIC {now}] {msg}", flush=True)
    except (OSError, RuntimeError):
        logger.debug("music source debug 출력 실패", exc_info=True)


class _SilentYTDLLogger:
    def debug(self, msg: str) -> None:
        return

    def info(self, msg: str) -> None:
        return

    def warning(self, msg: str) -> None:
        return

    def error(self, msg: str) -> None:
        return


YTDL_LOGGER = _SilentYTDLLogger()


def _detect_ffmpeg_executable() -> str:
    local_path = os.path.join("bin", "ffmpeg.exe")
    if os.path.exists(local_path):
        return local_path
    return "ffmpeg"


search_ytdl = youtube_dl.YoutubeDL(
    {
        "default_search": "auto",
        "extract_flat": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": YTDL_LOGGER,
    }
)

ytdl = youtube_dl.YoutubeDL(
    {
        "noplaylist": True,
        "skip_download": True,
        "simulate": True,
        "quiet": True,
        "verbose": False,
        "no_warnings": True,
        "logtostderr": False,
        "ignoreerrors": True,
        "nocheckcertificate": True,
        "logger": YTDL_LOGGER,
    }
)

info_ytdl = youtube_dl.YoutubeDL(
    {
        "noplaylist": True,
        "skip_download": True,
        "simulate": True,
        "quiet": True,
        "verbose": False,
        "no_warnings": True,
        "logtostderr": False,
        "ignoreerrors": True,
        "nocheckcertificate": True,
        "logger": YTDL_LOGGER,
    }
)


def build_ffmpeg_options(
    *,
    base_options: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    start_time: int = 0,
    header_target: Literal["before_options", "options"] = "before_options",
) -> dict[str, str]:
    options = dict(base_options or ffmpeg_options)
    if start_time > 0:
        options["options"] = f"-ss {start_time} " + options.get("options", "")

    if headers:
        header_str = "".join([f"{key}: {value}\r\n" for key, value in headers.items()])
        if header_target == "before_options":
            options["before_options"] = (
                f'-headers "{header_str}" ' + options.get("before_options", "")
            )
        else:
            options["options"] = options.get("options", "") + f' -headers "{header_str}"'
    return options


async def fetch_stream_url(page_url: str) -> str:
    dbg(f"fetch_stream_url: page_url={page_url}")
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(page_url) as resp:
            text = await resp.text()

    data = extract_initial_player_response(text)
    audio_formats = [
        fmt
        for fmt in (data.get("streamingData", {}).get("adaptiveFormats", []) or [])
        if str(fmt.get("mimeType", "")).startswith("audio/")
    ]
    dbg(f"fetch_stream_url: audio_formats_count={len(audio_formats)}")

    best = select_initial_audio_format(data)
    dbg(
        f"fetch_stream_url: selected avgBitrate={best.get('averageBitrate')} mime={best.get('mimeType')}"
    )
    return best["url"]


def _make_ydl_opts(**overrides: Any) -> dict[str, Any]:
    cookies_path = os.path.join(os.getcwd(), "cookies.txt")
    base = {
        "noplaylist": True,
        "skip_download": True,
        "simulate": True,
        "quiet": True,
        "verbose": False,
        "no_warnings": True,
        "logtostderr": False,
        "ignoreerrors": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "extractor_retries": 2,
        "source_address": "0.0.0.0",
        "logger": YTDL_LOGGER,
    }
    if os.path.exists(cookies_path):
        base["cookiefile"] = cookies_path
    base.update(overrides)
    return base


def _summarize_ydl_opts(opts: Mapping[str, Any]) -> str:
    parts = []
    extractor_args = opts.get("extractor_args", {}).get("youtube", {})
    player_client = extractor_args.get("player_client")
    if player_client:
        parts.append(f"pc={','.join(player_client)}")
    else:
        parts.append("pc=default")
    parts.append(f"hdr={'Y' if 'http_headers' in opts else 'N'}")
    return " ".join(parts)


def _extract_info_with_fallback(url: str) -> dict[str, Any]:
    dbg(f"_extract_info_with_fallback: url={url}")
    attempts = [
        _make_ydl_opts(
            extractor_args={"youtube": {"player_client": ["android", "web"]}},
            http_headers=HEADERS,
        ),
        _make_ydl_opts(http_headers=HEADERS),
        _make_ydl_opts(
            extractor_args={"youtube": {"player_client": ["android", "web", "ios"]}},
            http_headers=HEADERS,
        ),
        _make_ydl_opts(),
    ]
    last_err: BaseException | None = None
    for opts in attempts:
        try:
            with youtube_dl.YoutubeDL(opts) as ydl:
                dbg(f"_extract_info_with_fallback: using {_summarize_ydl_opts(opts)}")
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise ValueError("yt-dlp returned None")
                dbg(
                    f"_extract_info_with_fallback: got info type={type(info)} keys={list(info.keys()) if isinstance(info, dict) else None}"
                )
                return info
        except Exception as exc:
            dbg(f"_extract_info_with_fallback: attempt failed: {type(exc)} {exc}")
            last_err = exc
            continue
    raise ValueError(f"yt-dlp 메타 추출 실패: {type(last_err)} {last_err}")


async def fetch_stream_info(page_url: str) -> tuple[str, dict[str, Any]]:
    dbg(f"fetch_stream_info: page_url={page_url}")
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(page_url) as resp:
            text = await resp.text()

    player_response = extract_initial_player_response(text)
    audio_url, data = build_stream_info_from_player_response(
        player_response,
        page_url=page_url,
    )
    dbg(
        f"fetch_stream_info: title={data['title']} duration={data['duration']} uploader={data['uploader']} thumb={bool(data['thumbnail'])}"
    )
    return audio_url, data


class YTDLSource:
    def __init__(
        self,
        source: discord.FFmpegOpusAudio,
        *,
        data: dict[str, Any],
        requester: discord.User | None = None,
        audio_url: str | None = None,
    ) -> None:
        self.source = source
        self.data = data
        self.title = data.get("title")
        self.webpage_url = data.get("webpage_url")
        self.requester = requester
        self.audio_url = audio_url

    @classmethod
    async def from_url(
        cls,
        url: str,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        start_time: int = 0,
        requester: discord.User | None = None,
    ) -> "YTDLSource":
        dbg(
            f"YTDLSource.from_url: start url={url} start_time={start_time} requester={getattr(requester, 'id', None)}"
        )
        loop = loop or asyncio.get_event_loop()

        if not re.match(r"^https?://", url or ""):
            dbg("YTDLSource.from_url: keyword search path")
            search = f"ytsearch5:{url}"
            info = await loop.run_in_executor(
                YTDL_EXECUTOR, lambda: _extract_info_with_fallback(search)
            )
            url = resolve_search_result_url(info)
            dbg(f"YTDLSource.from_url: selected url={url}")

        try:
            data = await loop.run_in_executor(
                YTDL_EXECUTOR, lambda: _extract_info_with_fallback(url)
            )
        except Exception as exc:
            dbg(
                f"YTDLSource.from_url: yt-dlp failed -> HTML fallback: {type(exc)} {exc}"
            )
            audio_url, data = await fetch_stream_info(url)
            opts = build_ffmpeg_options(
                base_options=ffmpeg_options,
                headers=HEADERS,
                start_time=start_time,
                header_target="options",
            )
            ffmpeg_exec = _detect_ffmpeg_executable()
            dbg(
                f"YTDLSource.from_url: [fallback] creating FFmpegOpusAudio exec={ffmpeg_exec}"
            )
            source = discord.FFmpegOpusAudio(audio_url, **opts, executable=ffmpeg_exec)
            return cls(
                source=source,
                data=data,
                requester=requester,
                audio_url=audio_url,
            )

        if isinstance(data, dict):
            dbg(f"YTDLSource.from_url: meta keys={list(data.keys())}")
        else:
            dbg(f"YTDLSource.from_url: meta type={type(data)}")
        if data and "entries" in data:
            data = select_yt_dlp_entry(data)
        if not data:
            raise ValueError("메타데이터를 가져오지 못했습니다.")

        formats = data.get("formats", []) or []
        dbg(f"YTDLSource.from_url: formats_count={len(formats)}")
        best = select_best_audio_format(formats)
        if best:
            try:
                dbg(
                    f"YTDLSource.from_url: best abr={best.get('abr')} tbr={best.get('tbr')} acodec={best.get('acodec')} vcodec={best.get('vcodec')}"
                )
            except (AttributeError, TypeError):
                logger.debug("yt-dlp best format debug 출력 실패", exc_info=True)

        audio_url = None
        if best and best.get("url"):
            audio_url = best["url"]
        elif data.get("url"):
            audio_url = data["url"]
        else:
            try:
                page_url = data.get("webpage_url") or url
                audio_url = await fetch_stream_url(page_url)
            except Exception as exc:
                dbg(f"YTDLSource.from_url: fetch_stream_url 실패: {type(exc)} {exc}")
                raise
        dbg(f"YTDLSource.from_url: audio_url selected={bool(audio_url)}")

        opts = build_ffmpeg_options(
            base_options=ffmpeg_options,
            headers=HEADERS,
            start_time=start_time,
            header_target="before_options",
        )
        ffmpeg_exec = _detect_ffmpeg_executable()
        dbg(f"YTDLSource.from_url: creating FFmpegOpusAudio exec={ffmpeg_exec}")
        source = discord.FFmpegOpusAudio(audio_url, **opts, executable=ffmpeg_exec)
        return cls(source=source, data=data, requester=requester, audio_url=audio_url)
