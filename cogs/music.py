# cogs/music.py
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
import json as _json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Deque, Optional, Tuple, Coroutine, Any

import aiohttp
import discord
import yt_dlp as youtube_dl
from discord import Embed, Message, Object, TextChannel, app_commands
from discord.ext import commands
from discord.ui import Button, View
from discord.utils import utcnow
from util.channel_settings import get_channel
from util.db import execute_query, fetch_all
from util.music_favorites import (
    MUSIC_FAVORITE_SLOT_MAX,
    MusicFavorite,
    build_music_favorite_button_label,
    get_music_favorite,
    list_music_favorites,
    upsert_music_favorite,
    validate_music_favorite_slot,
)
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
H_BAR = "\u2015"
# 공통 상수
PANEL_TITLE = "🎵 신창섭의 다해줬잖아"
DEFAULT_MUSIC_CHANNEL_NAME = "🎵ㆍ神-음악채널"
MUSIC_CHANNEL_TYPE = "music"
MAX_QUEUE_DISPLAY = 10
IDLE_DISCONNECT_SECONDS = 300
MSG_NO_PLAYING = "❌ 재생 중인 음악이 없습니다."
UNKNOWN = "알 수 없음"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


# 간단한 디버그 로깅 헬퍼
def dbg(msg: str):
    try:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[MUSIC {now}] {msg}", flush=True)
    except (OSError, RuntimeError):
        logger.debug("music debug 출력 실패", exc_info=True)


# yt-dlp가 콘솔에 ERROR/경고를 직접 찍지 않도록 무음 로거 정의
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


ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-threads 2 -vn -ac 2 -ar 48000 -acodec libopus -compression_level 5 -application audio -hide_banner -nostats -loglevel error",
}

# yt-dlp 전용 쓰레드 풀(작게 제한) — 재생 중 추가 검색/추출이 이벤트 루프를 굶기지 않도록 격리
YTDL_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ytdl")


# FFmpeg 경로 자동 감지: 로컬 bin\\ffmpeg.exe가 있으면 사용, 없으면 시스템 PATH의 ffmpeg 사용
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
        # DASH/HLS 매니페스트 차단은 일부 영상에서 포맷 부재 오류를 유발할 수 있어 제거
        # "youtube_include_dash_manifest": False,
        # "youtube_include_hls_manifest": False,
        "logger": YTDL_LOGGER,
    }
)

# 포맷 강제 없이 메타/포맷 정보만 가져오는 용도 (에러 줄이기)
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
        # 포맷 선택은 우리 코드에서 수동으로
        "logger": YTDL_LOGGER,
    }
)


async def fetch_stream_url(page_url: str) -> str:
    dbg(f"fetch_stream_url: page_url={page_url}")
    # ① YouTube 페이지 HTML 한 번만 가져오기
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(page_url) as resp:
            text = await resp.text()

    # ② ytInitialPlayerResponse JSON 추출
    # 원본은 탐욕적/비탐욕적 정규식 사용. 안전하게 세미콜론 기준으로 캡쳐
    m = re.search(r"ytInitialPlayerResponse\s*=\s*(\{[^;]+\});", text)
    if not m:
        raise ValueError("ytInitialPlayerResponse not found in page")
    data = json.loads(m.group(1))

    # ③ adaptiveFormats 중 audio MIME만 필터
    af = data["streamingData"]["adaptiveFormats"]
    audio_formats = [f for f in af if f.get("mimeType", "").startswith("audio/")]
    dbg(f"fetch_stream_url: audio_formats_count={len(audio_formats)}")

    # ④ 비트레이트 최고 스트림 URL 선택
    best = max(audio_formats, key=lambda f: f.get("averageBitrate", 0))
    dbg(
        f"fetch_stream_url: selected avgBitrate={best.get('averageBitrate')} mime={best.get('mimeType')}"
    )
    return best["url"]


def _make_ydl_opts(**overrides):
    # cookies.txt가 있으면 사용할 수 있도록 옵션 구성
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
        # 포맷 선택은 필요 시 지정
    }
    if os.path.exists(cookies_path):
        base["cookiefile"] = cookies_path
    base.update(overrides)
    return base


def _extract_info_with_fallback(url: str):
    """yt-dlp 메타 추출을 여러 전략으로 시도한다."""
    dbg(f"_extract_info_with_fallback: url={url}")
    # 1순위: player_client를 android+web로 지정하고 헤더도 함께 전송 (현실적으로 가장 성공률이 높음)
    # 2순위: 기본 웹 헤더만 지정
    # 3순위: player_client 확장(android+web+ios) + 헤더
    # 4순위: 완전 기본값
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
    last_err = None

    def _summarize_opts(opts: dict) -> str:
        parts = []
        ex = opts.get("extractor_args", {}).get("youtube", {})
        pc = ex.get("player_client")
        if pc:
            parts.append(f"pc={','.join(pc)}")
        else:
            parts.append("pc=default")
        parts.append(f"hdr={'Y' if 'http_headers' in opts else 'N'}")
        return " ".join(parts)

    for opts in attempts:
        try:
            with youtube_dl.YoutubeDL(opts) as ydl:
                dbg(f"_extract_info_with_fallback: using {_summarize_opts(opts)}")
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise ValueError("yt-dlp returned None")
                dbg(
                    f"_extract_info_with_fallback: got info type={type(info)} keys={list(info.keys()) if isinstance(info,dict) else None}"
                )
                return info
        except Exception as e:
            dbg(f"_extract_info_with_fallback: attempt failed: {type(e)} {e}")
            last_err = e
            continue
    raise ValueError(f"yt-dlp 메타 추출 실패: {type(last_err)} {last_err}")


async def fetch_stream_info(page_url: str) -> tuple[str, dict]:
    """직접 HTML을 파싱해 오디오 스트림 URL과 최소 메타데이터를 반환합니다.
    반환: (audio_url, data)
    data에는 title, webpage_url, duration, uploader, thumbnail 등이 포함됩니다.
    """
    dbg(f"fetch_stream_info: page_url={page_url}")
    headers = HEADERS
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(page_url) as resp:
            text = await resp.text()

    m = re.search(r"ytInitialPlayerResponse\s*=\s*(\{[^;]+\});", text)
    if not m:
        raise ValueError("ytInitialPlayerResponse not found in page")
    j = json.loads(m.group(1))

    # 스트리밍 URL
    af = j.get("streamingData", {}).get("adaptiveFormats", [])
    audio_formats = [f for f in af if str(f.get("mimeType", "")).startswith("audio/")]
    if not audio_formats:
        raise ValueError("no audio formats in adaptiveFormats")
    best = max(audio_formats, key=lambda f: f.get("averageBitrate", 0))
    audio_url = best.get("url")

    # 메타데이터 구성
    vd = j.get("videoDetails", {})
    pmr = j.get("microformat", {}).get("playerMicroformatRenderer", {})
    # thumbnail
    thumb = None
    thumbs = (
        (pmr.get("thumbnail", {}) or {}).get("thumbnails")
        or (vd.get("thumbnail", {}) or {}).get("thumbnails")
        or []
    )
    if thumbs:
        thumb = thumbs[-1].get("url")
    data = {
        "title": vd.get("title"),
        "webpage_url": page_url,
        "duration": int(vd.get("lengthSeconds", 0) or 0),
        "uploader": vd.get("author") or pmr.get("ownerChannelName"),
        "thumbnail": thumb,
    }
    dbg(
        f"fetch_stream_info: title={data['title']} duration={data['duration']} uploader={data['uploader']} thumb={bool(thumb)}"
    )
    return audio_url, data


@dataclass
class GuildMusicState:
    player: Optional["YTDLSource"] = None
    start_ts: float = 0.0
    paused_at: Optional[float] = None
    queue: Deque["QueuedTrack"] = field(default_factory=collections.deque)
    control_channel: Optional[TextChannel] = None
    control_msg: Optional[Message] = None
    control_view: Optional[View] = None
    updater_task: Optional[asyncio.Task] = None
    idle_disconnect_task: Optional[asyncio.Task] = None
    is_loop: bool = False
    is_seeking: bool = False
    is_skipping: bool = False
    is_stopping: bool = False


@dataclass
class QueuedTrack:
    """대기열에 URL만 저장하는 경량 트랙"""

    url: str
    requester: Optional[discord.User] = None
    # 아래 메타는 백그라운드에서 채울 수 있음
    title: Optional[str] = None
    duration: int = 0
    webpage_url: Optional[str] = None
    uploader: Optional[str] = None
    thumbnail: Optional[str] = None
    added_at: float = field(default_factory=lambda: time.time())


def parse_seek_seconds(value: str) -> int:
    text = (value or "").strip()
    if not text:
        raise ValueError("시간을 입력해 주세요.")

    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("시간 형식이 올바르지 않습니다.")
        minutes, seconds = (int(parts[0]), int(parts[1]))
        if seconds >= 60:
            raise ValueError("초는 0~59 사이여야 합니다.")
        total = minutes * 60 + seconds
    else:
        if not text.isdigit():
            raise ValueError("시간 형식이 올바르지 않습니다.")
        total = int(text)

    if total < 0:
        raise ValueError("시간은 0초 이상이어야 합니다.")
    return total


def _validate_queue_position(queue: Deque[QueuedTrack], position: int) -> int:
    if position < 1 or position > len(queue):
        raise ValueError(f"대기열 번호는 1~{len(queue)} 사이여야 합니다.")
    return position - 1


def remove_queue_track(queue: Deque[QueuedTrack], position: int) -> QueuedTrack:
    index = _validate_queue_position(queue, position)
    tracks = list(queue)
    removed = tracks.pop(index)
    queue.clear()
    queue.extend(tracks)
    return removed


def move_queue_track(
    queue: Deque[QueuedTrack], current_position: int, new_position: int
) -> QueuedTrack:
    current_index = _validate_queue_position(queue, current_position)
    if new_position < 1 or new_position > len(queue):
        raise ValueError(f"이동 위치는 1~{len(queue)} 사이여야 합니다.")

    tracks = list(queue)
    moved = tracks.pop(current_index)
    tracks.insert(new_position - 1, moved)
    queue.clear()
    queue.extend(tracks)
    return moved


def shuffle_queue(
    queue: Deque[QueuedTrack], randomizer: Optional[random.Random] = None
) -> None:
    tracks = list(queue)
    rng = randomizer or random
    rng.shuffle(tracks)
    queue.clear()
    queue.extend(tracks)


def _track_title(track: QueuedTrack) -> str:
    return track.title or track.webpage_url or track.url or "(제목 정보 없음)"


def build_queue_preview(
    queue: Deque[QueuedTrack],
    *,
    limit: int = 3,
    title_limit: int = 28,
) -> Optional[Tuple[str, str]]:
    if not queue:
        return None

    def _shorten(title: str) -> str:
        if len(title) <= title_limit:
            return title
        return f"{title[:title_limit]}…"

    lines = [
        f"`{index}` {_shorten(_track_title(track))}"
        for index, track in enumerate(list(queue)[:limit], start=1)
    ]
    remaining = len(queue) - limit
    if remaining > 0:
        lines.append(f"+ {remaining}곡 더")
    return f"대기열({len(queue)}개)", "\n".join(lines)


def _favorite_by_slot(favorites: list[MusicFavorite]) -> dict[int, MusicFavorite]:
    return {favorite.slot: favorite for favorite in favorites}


def _normalize_search_entry_url(entry: dict) -> str:
    raw_url = entry.get("webpage_url") or entry.get("url") or ""
    if raw_url.startswith("/watch"):
        return f"https://www.youtube.com{raw_url}"
    return raw_url


class YTDLSource:
    def __init__(
        self,
        source: discord.FFmpegOpusAudio,
        *,
        data,
        requester: discord.User = None,
        audio_url: Optional[str] = None,
    ):
        self.source = source
        self.data = data
        self.title = data.get("title")
        self.webpage_url = data.get("webpage_url")
        self.requester = requester
        self.audio_url = audio_url  # 재시작/루프 시 재사용할 실제 스트림 URL

    @classmethod
    async def from_url(
        cls, url, *, loop=None, start_time: int = 0, requester: discord.User = None
    ):
        dbg(
            f"YTDLSource.from_url: start url={url} start_time={start_time} requester={getattr(requester,'id',None)}"
        )
        loop = loop or asyncio.get_event_loop()

        # ! 검색어면 먼저 ID/URL만 빠르게 가져오기(안전 처리)
        if not re.match(r"^https?://", url or ""):
            dbg("YTDLSource.from_url: keyword search path")
            search = f"ytsearch5:{url}"
            info = await loop.run_in_executor(
                YTDL_EXECUTOR, lambda: _extract_info_with_fallback(search)
            )
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise ValueError("검색 결과가 없습니다.")
            entry = entries[0]
            vid = entry.get("id")
            url = (
                entry.get("webpage_url")
                or entry.get("url")
                or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
            )
            if not url:
                raise ValueError("검색 결과 URL이 없습니다.")
            dbg(f"YTDLSource.from_url: selected url={url}")

        # ! 실제 메타·스트림 준비
        try:
            data = await loop.run_in_executor(
                YTDL_EXECUTOR, lambda: _extract_info_with_fallback(url)
            )
        except Exception as e:
            # yt-dlp가 완전히 실패하는 경우: HTML 파싱 기반 완전 대체 경로
            dbg(f"YTDLSource.from_url: yt-dlp failed -> HTML fallback: {type(e)} {e}")
            audio_url, data = await fetch_stream_info(url)
            # ffmpeg 옵션 구성
            opts = ffmpeg_options.copy()
            if start_time > 0:
                opts["options"] = f"-ss {start_time} " + opts["options"]
            if HEADERS:
                header_str = "".join([f"{k}: {v}\r\n" for k, v in HEADERS.items()])
                opts["options"] = opts["options"] + f' -headers "{header_str}"'
            ffmpeg_exec = _detect_ffmpeg_executable()
            dbg(
                f"YTDLSource.from_url: [fallback] creating FFmpegOpusAudio exec={ffmpeg_exec}"
            )
            source = discord.FFmpegOpusAudio(audio_url, **opts, executable=ffmpeg_exec)
            return cls(
                source=source, data=data, requester=requester, audio_url=audio_url
            )
        if isinstance(data, dict):
            dbg(f"YTDLSource.from_url: meta keys={list(data.keys())}")
        else:
            dbg(f"YTDLSource.from_url: meta type={type(data)}")
        # ! 단일 비디오인 경우
        if data and "entries" in data:
            # 첫 유효 항목 선택(포맷이 있는 엔트리 우선)
            entries = [e for e in (data.get("entries") or []) if e]
            data = next(
                (e for e in entries if e.get("formats")),
                entries[0] if entries else data,
            )
        if not data:
            raise ValueError("메타데이터를 가져오지 못했습니다.")

        # ! 포맷 리스트 중 bestaudio 뽑기
        formats = data.get("formats", []) or []
        dbg(f"YTDLSource.from_url: formats_count={len(formats)}")
        # 상세 포맷 전체 덤프는 소음이 커서 생략
        best = None
        if formats:
            # 1) 진짜 오디오만 우선 (audio_ext != 'none' && acodec != 'none')
            strict_audio = [
                f
                for f in formats
                if (f.get("audio_ext") and f.get("audio_ext") != "none")
                and (str(f.get("acodec", "none")) != "none")
                and f.get("url")
            ]
            # 2) vcodec == 'none' 이지만 acodec/abr가 의미있는 후보
            loose_audio = [
                f
                for f in formats
                if str(f.get("vcodec", "none")) == "none"
                and f.get("url")
                and ((f.get("abr") or 0) > 0 or str(f.get("acodec", "none")) != "none")
            ]
            candidates = strict_audio or loose_audio or formats

            def _rate_key(f):
                # abr > asr > tbr > 0
                return (f.get("abr") or 0, f.get("asr") or 0, f.get("tbr") or 0)

            best = max(candidates, key=_rate_key)
            try:
                dbg(
                    f"YTDLSource.from_url: best abr={best.get('abr')} tbr={best.get('tbr')} acodec={best.get('acodec')} vcodec={best.get('vcodec')}"
                )
            except (AttributeError, TypeError):
                logger.debug("yt-dlp best format debug 출력 실패", exc_info=True)

        # yt-dlp가 고른 직접 URL (format 지정 결과) fallback
        audio_url = None
        if best and best.get("url"):
            audio_url = best["url"]
        elif data.get("url"):
            audio_url = data["url"]
        else:
            # 최후 수단: 웹페이지 URL에서 직접 추출 시도
            try:
                page_url = data.get("webpage_url") or url
                audio_url = await fetch_stream_url(page_url)
            except Exception as e:
                dbg(f"YTDLSource.from_url: fetch_stream_url 실패: {type(e)} {e}")
                raise
        dbg(f"YTDLSource.from_url: audio_url selected={bool(audio_url)}")

        # ! ffmpeg 에 -ss(start_time) 옵션 및 HTTP 헤더 추가
        opts = ffmpeg_options.copy()
        if start_time > 0:
            opts["options"] = f"-ss {start_time} " + opts["options"]
        if HEADERS:
            header_str = "".join([f"{k}: {v}\r\n" for k, v in HEADERS.items()])
            # 입력에 적용되도록 before_options에 넣는다
            opts["before_options"] = (
                f'-headers "{header_str}" ' + opts["before_options"]
            )
        # ffmpeg 경로 결정
        ffmpeg_exec = _detect_ffmpeg_executable()
        dbg(f"YTDLSource.from_url: creating FFmpegOpusAudio exec={ffmpeg_exec}")
        source = discord.FFmpegOpusAudio(audio_url, **opts, executable=ffmpeg_exec)
        return cls(source=source, data=data, requester=requester, audio_url=audio_url)


# 검색 결과 뷰
class SearchResultView(View):
    def __init__(
        self,
        cog,
        videos: list[dict],
        *,
        favorite_slot: int | None = None,
    ):
        # 검색 결과를 최대 10개까지 숫자 버튼으로 제공
        super().__init__(timeout=120)
        self.cog = cog
        self.favorite_slot = favorite_slot

        vids = list(videos[:10])
        if not vids:
            self.add_item(
                Button(
                    label="❌ 검색 결과가 없습니다",
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                )
            )
            return

        # 1~10까지 번호 버튼 생성 (행: 5개씩 두 줄)
        for i, v in enumerate(vids, start=1):
            url = v.get("url")
            if not isinstance(url, str):
                continue
            btn = Button(
                label=str(i),
                style=discord.ButtonStyle.secondary,
                custom_id=f"search_pick_{i}",
                row=(i - 1) // 5,
            )

            async def _on_pick(interaction: discord.Interaction, _entry=v):
                # 즉시 재생(또는 대기열 추가), 메타 함께 전달
                await interaction.response.edit_message(
                    content="선택 처리 중...",
                    embed=None,
                    view=None,
                    delete_after=0.1,
                )
                if self.favorite_slot is not None:
                    await self.cog._save_search_entry_as_favorite(
                        interaction,
                        self.favorite_slot,
                        _entry,
                    )
                    return
                await self.cog._play_from_search_pick(interaction, _entry)

            btn.callback = _on_pick
            self.add_item(btn)


def _add_music_favorite_buttons(
    view: View,
    cog: "MusicCog",
    favorites: list[MusicFavorite],
    *,
    row: int,
) -> None:
    favorite_map = _favorite_by_slot(favorites)
    for slot in range(1, MUSIC_FAVORITE_SLOT_MAX + 1):
        favorite = favorite_map.get(slot)
        btn = Button(
            label=build_music_favorite_button_label(slot, favorite),
            style=discord.ButtonStyle.secondary,
            custom_id=f"music_favorite_play_{slot}",
            row=row,
            disabled=favorite is None,
        )

        async def _on_favorite(
            interaction: discord.Interaction,
            _slot: int = slot,
        ):
            await cog._play_music_favorite(interaction, _slot)

        btn.callback = _on_favorite
        view.add_item(btn)


class FavoriteSearchModal(discord.ui.Modal, title="즐겨찾기 음악 검색"):
    query = discord.ui.TextInput(
        label="저장할 음악 제목이나 링크",
        placeholder='예: "신창섭 다해줬잖아" or https://www.youtube.com/watch?v=...',
    )

    def __init__(self, cog: "MusicCog", slot: int):
        super().__init__()
        self.cog = cog
        self.slot = validate_music_favorite_slot(slot)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._search_music_for_favorite_slot(
            interaction,
            self.slot,
            str(self.query.value or ""),
        )


class MusicFavoriteSlotSelect(discord.ui.Select):
    def __init__(self, parent: "MusicFavoriteManageView"):
        self.manager_view = parent
        favorite_map = _favorite_by_slot(parent.favorites)
        options = []
        for slot in range(1, MUSIC_FAVORITE_SLOT_MAX + 1):
            favorite = favorite_map.get(slot)
            label = build_music_favorite_button_label(slot, favorite)
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(slot),
                    default=slot == parent.selected_slot,
                )
            )
        super().__init__(
            placeholder="수정할 즐겨찾기 번호 선택",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self.manager_view.selected_slot = int(self.values[0])
        for option in self.options:
            option.default = option.value == self.values[0]
        await interaction.response.edit_message(
            content=self.manager_view.status_text(),
            view=self.manager_view,
        )


class MusicFavoriteManageView(View):
    def __init__(
        self,
        cog: "MusicCog",
        *,
        guild_id: int,
        favorites: list[MusicFavorite],
        current_track: MusicFavorite | None = None,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = int(guild_id)
        self.favorites = list(favorites)
        self.current_track = current_track
        self.selected_slot = 1
        self.add_item(MusicFavoriteSlotSelect(self))

        search_btn = Button(
            label="🔎 검색해서 저장",
            style=discord.ButtonStyle.primary,
            custom_id="music_favorite_search",
            row=1,
        )
        current_btn = Button(
            label="⭐ 현재곡 저장",
            style=discord.ButtonStyle.success,
            custom_id="music_favorite_current",
            row=1,
            disabled=current_track is None,
        )
        search_btn.callback = self._on_search
        current_btn.callback = self._on_current
        self.add_item(search_btn)
        self.add_item(current_btn)

    def status_text(self) -> str:
        return f"저장/수정할 즐겨찾기 슬롯: **{self.selected_slot}번**"

    async def _on_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            FavoriteSearchModal(self.cog, self.selected_slot)
        )

    async def _on_current(self, interaction: discord.Interaction):
        await self.cog._save_current_track_as_favorite(
            interaction,
            self.selected_slot,
        )


# ! 기본 임베드에 붙을 뷰
class MusicHelperView(View):
    def __init__(
        self,
        cog: "MusicCog",
        favorites: list[MusicFavorite] | None = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        favorites = favorites or []

        search_btn = Button(
            label="🔍 검색",
            style=discord.ButtonStyle.primary,
            custom_id="music_search",
            row=0,
        )
        favorite_btn = Button(
            label="⭐ 즐겨찾기",
            style=discord.ButtonStyle.secondary,
            custom_id="music_favorite_manage",
            row=0,
        )
        search_btn.callback = self._on_search
        favorite_btn.callback = self._on_favorite_manage
        self.add_item(search_btn)
        self.add_item(favorite_btn)
        _add_music_favorite_buttons(self, cog, favorites, row=1)

    async def _on_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SearchModal(self.cog))

    async def _on_favorite_manage(self, interaction: discord.Interaction):
        await self.cog._open_music_favorite_manager(interaction)


# ! 음악 재생시 붙을 뷰
class MusicControlView(View):
    def __init__(
        self,
        cog: "MusicCog",
        state: "GuildMusicState",
        favorites: list[MusicFavorite] | None = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state
        self.favorites = favorites or []

        # ▶️ 다시재생 또는 ⏸️ 일시정지 버튼
        if state.paused_at:
            self.resume_btn = Button(
                label="▶️ 다시재생",
                style=discord.ButtonStyle.primary,
                custom_id="music_resume",
                row=0,
            )
            self.resume_btn.callback = self._on_resume
            self.add_item(self.resume_btn)
        else:
            self.pause_btn = Button(
                label="⏸️ 일시정지",
                style=discord.ButtonStyle.primary,
                custom_id="music_pause",
                row=0,
            )
            self.pause_btn.callback = self._on_pause
            self.add_item(self.pause_btn)

        # 나머지 버튼들
        self.add_control_buttons()
        _add_music_favorite_buttons(self, cog, self.favorites, row=3)

    def add_control_buttons(self):
        skip_btn = Button(
            label="⏭️ 스킵",
            style=discord.ButtonStyle.success,
            custom_id="music_skip",
            row=0,
        )
        stop_btn = Button(
            label="⏹️ 정지",
            style=discord.ButtonStyle.danger,
            custom_id="music_stop",
            row=0,
        )
        queue_btn = Button(
            label="🔀 대기열",
            style=discord.ButtonStyle.secondary,
            custom_id="music_queue",
            row=1,
        )
        seek_btn = Button(
            label="⏩ 구간이동",
            style=discord.ButtonStyle.secondary,
            custom_id="music_seek",
            row=1,
        )
        loop_btn = Button(
            label="🔁 반복",
            style=discord.ButtonStyle.secondary,
            custom_id="music_loop",
            row=1,
        )
        search_btn = Button(
            label="🔍 검색",
            style=discord.ButtonStyle.primary,
            custom_id="music_search_2",
            row=2,
        )
        favorite_btn = Button(
            label="⭐ 즐겨찾기",
            style=discord.ButtonStyle.secondary,
            custom_id="music_favorite_manage",
            row=2,
        )

        skip_btn.callback = self._on_skip
        stop_btn.callback = self._on_stop
        queue_btn.callback = self._on_queue
        seek_btn.callback = self._on_seek
        loop_btn.callback = self._on_loop
        search_btn.callback = self._on_search
        favorite_btn.callback = self._on_favorite_manage

        for b in [
            skip_btn,
            stop_btn,
            queue_btn,
            seek_btn,
            loop_btn,
            search_btn,
            favorite_btn,
        ]:
            self.add_item(b)

    # === 콜백 함수들 ===
    async def _on_pause(self, interaction: discord.Interaction):
        await self.cog._pause(interaction)

    async def _on_resume(self, interaction: discord.Interaction):
        await self.cog._resume(interaction)

    async def _on_skip(self, interaction: discord.Interaction):
        await self.cog._skip(interaction)

    async def _on_stop(self, interaction: discord.Interaction):
        await self.cog._stop(interaction)

    async def _on_queue(self, interaction: discord.Interaction):
        await self.cog._show_queue(interaction)

    async def _on_seek(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SeekModal(self.cog))

    async def _on_loop(self, interaction: discord.Interaction):
        await self.cog._toggle_loop(interaction)

    async def _on_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SearchModal(self.cog))

    async def _on_favorite_manage(self, interaction: discord.Interaction):
        await self.cog._open_music_favorite_manager(interaction)


# ! 구간 탐색 모달
class SeekModal(discord.ui.Modal, title="구간이동"):
    time = discord.ui.TextInput(
        label="가록될 시간 (mm:ss 또는 초)", placeholder="예: 1:23 또는 83"
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        t = (self.time.value or "").strip()
        try:
            seconds = parse_seek_seconds(t)
        except ValueError:
            # 입력 형식 오류에 대해 반드시 응답하여 상호작용 실패를 방지
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ 시간 형식이 올바르지 않습니다. 예: 1:23 또는 83", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "❌ 시간 형식이 올바르지 않습니다. 예: 1:23 또는 83", ephemeral=True
                )
            return
        await self.cog._seek(interaction, seconds)


# ! 음악 검색 버튼 누르면 열릴 모달
class SearchModal(discord.ui.Modal, title="음악검색"):
    query = discord.ui.TextInput(
        label="음악의 제목이나 링크를 입력하세요",
        placeholder='예: "신창섭 다해줬잖아" or https://www.youtube.com/watch?v=DYbt8rmJT40',
    )

    def __init__(self, cog: "MusicCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._play(interaction, self.query.value)


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}  # 길드별 상태 저장
        # 백그라운드 태스크 레퍼런스 보관(조기 GC 방지)
        self._bg_tasks: set[asyncio.Task] = set()
        # 패널 메시지 ID 저장 로드
        self._panel_ids: dict[str, int] = {}
        # 음악 채널 일반 채팅 자동삭제 경고 쿨다운 관리
        self._last_warn: dict[int, float] = {}
        self._warn_cooldown = 10.0  # 초
        # 부팅시 1회 정리 수행 여부
        self._purged_guilds: set[int] = set()
        self._favorite_cache: dict[int, list[MusicFavorite]] = {}

    # === 패널 ID 저장/로드 유틸 ===
    async def cog_load(self):
        self._panel_ids = await self._load_panel_ids()

    async def _load_panel_ids(self) -> dict[str, int]:
        try:
            query = "SELECT guild_id, message_id FROM panel_messages"
            rows = await fetch_all(query)
            res = {}
            for r in rows:
                res[str(r["guild_id"])] = int(r["message_id"])
            return res
        except Exception:
            logger.warning("패널 ID DB 로드 실패", exc_info=True)
            return {}

    async def _set_panel_id(self, guild_id, message_id):
        self._panel_ids[str(guild_id)] = int(message_id)
        query = "INSERT INTO panel_messages (guild_id, message_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE message_id = %s"
        await execute_query(query, (int(guild_id), int(message_id), int(message_id)))

    async def _del_panel_id(self, guild_id):
        self._panel_ids.pop(str(guild_id), None)
        query = "DELETE FROM panel_messages WHERE guild_id = %s"
        await execute_query(query, (int(guild_id),))

    def _spawn_bg(self, coro: "Coroutine[Any, Any, Any]") -> asyncio.Task:
        """백그라운드 태스크를 등록하고 레퍼런스를 보관한다."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)

        def _log_and_discard(done_task: asyncio.Task) -> None:
            self._bg_tasks.discard(done_task)
            try:
                exception = done_task.exception()
            except asyncio.CancelledError:
                return
            if exception is not None:
                logger.exception(
                    "music background task failed",
                    exc_info=(type(exception), exception, exception.__traceback__),
                )

        task.add_done_callback(_log_and_discard)
        return task

    async def _load_music_favorites(
        self,
        guild_id: int,
        *,
        refresh: bool = False,
    ) -> list[MusicFavorite]:
        if not refresh and guild_id in self._favorite_cache:
            return self._favorite_cache[guild_id]
        try:
            favorites = await list_music_favorites(guild_id)
        except Exception as e:
            dbg(f"_load_music_favorites: failed guild={guild_id} {type(e)} {e}")
            favorites = []
        self._favorite_cache[guild_id] = favorites
        return favorites

    async def _build_helper_view(self, guild_id: int) -> MusicHelperView:
        favorites = await self._load_music_favorites(guild_id)
        return MusicHelperView(self, favorites)

    async def _build_control_view(
        self,
        guild_id: int,
        state: GuildMusicState,
    ) -> MusicControlView:
        favorites = await self._load_music_favorites(guild_id)
        return MusicControlView(self, state, favorites)

    def _current_player_as_favorite(
        self,
        guild_id: int,
        player: Optional["YTDLSource"],
    ) -> MusicFavorite | None:
        if player is None:
            return None
        url = player.webpage_url or player.data.get("webpage_url") or ""
        if not url:
            return None
        return MusicFavorite(
            guild_id=guild_id,
            slot=1,
            title=player.title or player.data.get("title") or "(제목 정보 없음)",
            url=url,
            duration=int(player.data.get("duration") or 0),
            uploader=player.data.get("uploader"),
            thumbnail=player.data.get("thumbnail"),
        )

    async def _fill_queue_meta(self, track: "QueuedTrack"):
        """대기열 트랙의 가벼운 메타데이터를 채운다(재생에 영향 없음)."""
        try:
            loop = asyncio.get_event_loop()

            def _extract():
                try:
                    return info_ytdl.extract_info(track.url, download=False)
                except Exception:
                    logger.debug("대기열 메타데이터 추출 실패: url=%s", track.url, exc_info=True)
                    return None

            info = await loop.run_in_executor(YTDL_EXECUTOR, _extract)
            if not info or not isinstance(info, dict):
                return
            # 단일 엔트리 처리
            if "entries" in info and info.get("entries"):
                info = (info.get("entries") or [None])[0] or info
            track.title = info.get("title") or track.title
            track.duration = int(info.get("duration") or 0) or track.duration
            track.webpage_url = (
                info.get("webpage_url") or track.webpage_url or track.url
            )
            track.uploader = info.get("uploader") or track.uploader
            # 썸네일은 여러 키가 있을 수 있음
            track.thumbnail = (
                info.get("thumbnail")
                or (info.get("thumbnails") or [{}])[-1].get("url")
                or track.thumbnail
            )
        except Exception as e:
            dbg(f"_fill_queue_meta: failed {type(e)} {e}")

    async def _open_music_favorite_manager(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        favorites = await self._load_music_favorites(guild_id, refresh=True)
        state = self._get_state(guild_id)
        current_track = self._current_player_as_favorite(guild_id, state.player)
        view = MusicFavoriteManageView(
            self,
            guild_id=guild_id,
            favorites=favorites,
            current_track=current_track,
        )
        await interaction.followup.send(
            view.status_text(),
            view=view,
            ephemeral=True,
        )

    async def _search_music_for_favorite_slot(
        self,
        interaction: discord.Interaction,
        slot: int,
        query: str,
    ) -> None:
        slot = validate_music_favorite_slot(slot)
        query = (query or "").strip()
        if not query:
            await interaction.response.send_message(
                "❌ 검색어를 입력해 주세요.",
                ephemeral=True,
            )
            return

        info = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: search_ytdl.extract_info(f"ytsearch10:{query}", download=False),
        )
        raw = info.get("entries", []) or []
        videos = [
            entry
            for entry in raw
            if isinstance(entry.get("url"), str) and "watch?v=" in entry["url"]
        ][:10]
        if not videos:
            await interaction.response.send_message(
                "❌ 검색 결과가 없습니다.",
                ephemeral=True,
            )
            return

        description = "\n".join(
            f"{index + 1}. {video.get('title', '-')}"
            for index, video in enumerate(videos)
        )
        embed = Embed(
            title=f"⭐ {slot}번 즐겨찾기에 저장할 음악 선택",
            description=description,
            color=0xFFC0CB,
        )
        view = SearchResultView(self, videos, favorite_slot=slot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _save_music_favorite(
        self,
        interaction: discord.Interaction,
        *,
        slot: int,
        title: str,
        url: str,
        duration: int = 0,
        uploader: str | None = None,
        thumbnail: str | None = None,
    ) -> None:
        guild_id = interaction.guild.id
        await upsert_music_favorite(
            guild_id=guild_id,
            slot=slot,
            title=title,
            url=url,
            duration=duration,
            uploader=uploader,
            thumbnail=thumbnail,
            updated_by=interaction.user.id,
        )
        await self._load_music_favorites(guild_id, refresh=True)
        await self._refresh_music_panel_for_favorites(guild_id)
        msg = await interaction.followup.send(
            f"⭐ {slot}번 즐겨찾기에 **{title}** 저장했습니다.",
            ephemeral=True,
        )
        self._spawn_bg(self._auto_delete(msg, 5.0))

    async def _save_search_entry_as_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
        entry: dict,
    ) -> None:
        url = _normalize_search_entry_url(entry)
        await self._save_music_favorite(
            interaction,
            slot=slot,
            title=entry.get("title") or "(제목 정보 없음)",
            url=url,
            duration=int(entry.get("duration") or 0) if entry.get("duration") else 0,
            uploader=entry.get("uploader") or entry.get("channel") or None,
            thumbnail=(
                entry.get("thumbnail")
                or (entry.get("thumbnails") or [{}])[-1].get("url")
            ),
        )

    async def _save_current_track_as_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        favorite = self._current_player_as_favorite(guild_id, state.player)
        if favorite is None:
            await self._send_auto_delete(
                interaction,
                "❌ 현재 재생 중인 곡 정보가 없습니다.",
            )
            return
        await self._save_music_favorite(
            interaction,
            slot=slot,
            title=favorite.title,
            url=favorite.url,
            duration=favorite.duration,
            uploader=favorite.uploader,
            thumbnail=favorite.thumbnail,
        )

    async def _refresh_music_panel_for_favorites(self, guild_id: int) -> None:
        state = self._get_state(guild_id)
        if state.control_msg is None or state.control_channel is None:
            return
        if state.player:
            state.control_view = await self._build_control_view(guild_id, state)
            elapsed = int(time.time() - state.start_ts) if state.start_ts else 0
            embed = self._make_playing_embed(state.player, guild_id, elapsed)
        else:
            state.control_view = await self._build_helper_view(guild_id)
            embed = self._make_default_embed()
        await self._edit_msg(state, embed, state.control_view)

    async def _play_music_favorite(
        self,
        interaction: discord.Interaction,
        slot: int,
    ) -> None:
        slot = validate_music_favorite_slot(slot)
        favorite = await get_music_favorite(interaction.guild.id, slot)
        if favorite is None:
            await interaction.response.send_message(
                f"❌ {slot}번 즐겨찾기가 비어있습니다.",
                ephemeral=True,
            )
            return
        await self._play_url_now(
            interaction,
            favorite.url,
            success_prefix="⭐ 즐겨찾기 재생",
        )

    async def _play_from_search_pick(
        self, interaction: discord.Interaction, entry: dict
    ):
        """검색 버튼 선택 시, 가능한 메타를 최대한 채워서 바로 재생/대기열 추가"""
        # yt 검색 결과는 url이 상대 경로일 수 있어 보정
        url = _normalize_search_entry_url(entry)

        # 이미 재생 중이면 대기열에 메타 포함 추가
        voice_client = interaction.guild.voice_client
        state = self._get_state(interaction.guild.id)
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            error = self._same_voice_channel_error(interaction, voice_client)
            if error:
                msg = await interaction.followup.send(error, ephemeral=True)
                self._spawn_bg(self._auto_delete(msg, 5.0))
                return
            track = QueuedTrack(
                url=url,
                requester=interaction.user,
                title=entry.get("title") or None,
                duration=(
                    int(entry.get("duration") or 0) if entry.get("duration") else 0
                ),
                webpage_url=entry.get("webpage_url") or url,
                uploader=entry.get("uploader") or entry.get("channel") or None,
                thumbnail=(
                    (
                        entry.get("thumbnail")
                        or (entry.get("thumbnails") or [{}])[-1].get("url")
                    )
                    if isinstance(entry, dict)
                    else None
                ),
            )
            state.queue.append(track)
            # 보강 메타 필요시 백그라운드로 채우기
            self._spawn_bg(self._fill_queue_meta(track))
            msg = await interaction.followup.send(
                "▶ **대기열에 추가되었습니다.**", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return

        # 재생 중이 아니면 기존 _play 경로로 위임
        await self._play(interaction, url, skip_defer=True)

    # !길드의 State 리턴
    def _get_state(self, guild_id: int) -> GuildMusicState:
        return self.states.setdefault(guild_id, GuildMusicState())

    def _user_voice_channel(self, interaction: discord.Interaction):
        voice_state = getattr(interaction.user, "voice", None)
        return getattr(voice_state, "channel", None)

    def _same_voice_channel_error(
        self,
        interaction: discord.Interaction,
        voice_client=None,
    ) -> Optional[str]:
        voice_client = voice_client or getattr(interaction.guild, "voice_client", None)
        bot_channel = getattr(voice_client, "channel", None)
        if bot_channel is None:
            return None

        user_channel = self._user_voice_channel(interaction)
        if user_channel != bot_channel:
            return "❌ 같은 음성 채널에 있는 사용자만 음악을 제어할 수 있습니다."
        return None

    async def _send_auto_delete(
        self,
        interaction: discord.Interaction,
        content: str,
        *,
        delay: float = 5.0,
    ) -> None:
        msg = await interaction.followup.send(content, ephemeral=True)
        self._spawn_bg(self._auto_delete(msg, delay))

    async def _resolve_music_channel(
        self, guild: discord.Guild
    ) -> Optional[TextChannel]:
        state = self._get_state(guild.id)
        configured_channel_id = await get_channel(guild.id, MUSIC_CHANNEL_TYPE)
        if configured_channel_id:
            configured = guild.get_channel(configured_channel_id)
            if isinstance(configured, TextChannel):
                return configured

        if isinstance(state.control_channel, TextChannel):
            return state.control_channel

        return discord.utils.get(guild.text_channels, name=DEFAULT_MUSIC_CHANNEL_NAME)

    async def _is_music_control_channel(self, message: discord.Message) -> bool:
        if not message.guild:
            return False

        state = self._get_state(message.guild.id)
        if state.control_channel and message.channel.id == state.control_channel.id:
            return True
        if message.channel.name == DEFAULT_MUSIC_CHANNEL_NAME:
            return True

        configured_channel_id = await get_channel(message.guild.id, MUSIC_CHANNEL_TYPE)
        return bool(configured_channel_id and message.channel.id == configured_channel_id)

    def make_timeline_line(self, elapsed: int, total: int, length: int = 16) -> str:
        def format_time(seconds: int) -> str:
            m, s = divmod(seconds, 60)
            return f"{m:02}:{s:02}"

        """───01:26──03:37 (39%)"""
        elapsed_fmt = format_time(elapsed)
        total_fmt = format_time(total)
        pct = int(elapsed / total * 100) if total else 0
        _, filled = self.make_progress_bar(elapsed, total, length)
        left = H_BAR * filled
        right = H_BAR * (length - filled)
        return f"{left}{elapsed_fmt}{right} {total_fmt} ({pct}%)"

    def make_progress_bar(
        self, elapsed: int, total: int, length: int = 23
    ) -> Tuple[str, int]:
        if total == 0:
            return "▱" * length, 0
        filled = int(length * elapsed / total)
        return "▰" * filled + "▱" * (length - filled), filled

    # ?완
    # !메시지 수정(임베드, 뷰)
    async def _edit_msg(self, state, embed, view):
        # 기존 메시지 재사용. 존재하지 않거나 삭제된 경우만 새로 생성
        try:
            if state.control_msg is None:
                state.control_msg = await state.control_channel.send(
                    embed=embed, view=view
                )
                # 새로 만든 경우 저장
                if state.control_channel and state.control_channel.guild:
                    gid = str(state.control_channel.guild.id)
                    await self._set_panel_id(gid, state.control_msg.id)
                return
            await state.control_msg.edit(embed=embed, view=view)
        except discord.HTTPException as e:
            if getattr(e, "code", None) == 10008:  # Unknown Message
                print("[INFO] 패널 메시지가 사라져 새로 생성합니다.")
                state.control_msg = await state.control_channel.send(
                    embed=embed, view=view
                )
                if state.control_channel and state.control_channel.guild:
                    gid = str(state.control_channel.guild.id)
                    await self._set_panel_id(gid, state.control_msg.id)
            else:
                logger.warning("패널 업데이트 실패", exc_info=True)

    # ?완
    # ! 노래 재생 상황 업데이트 루프
    async def _updater_loop(self, guild_id: int):
        state = self._get_state(guild_id)
        try:
            dbg("_updater_loop: start")
            while state.player:
                voice_client = state.control_msg.guild.voice_client
                # ! voice_client 연결 끊김
                if not voice_client:
                    dbg("_updater_loop: voice_client disconnected")
                    await self._force_stop(guild_id)
                    return
                # ! 봇만 남아있음 → 종료 호출
                if voice_client and len(voice_client.channel.members) == 1:
                    dbg("_updater_loop: bot alone in channel, stopping")
                    await self._force_stop(guild_id)
                    return
                # ! 일시정지 대기
                if voice_client.is_paused():
                    dbg("_updater_loop: paused")
                    await asyncio.sleep(1)
                    continue
                # ! 재생시간 계산
                elapsed = int(time.time() - state.start_ts)
                total = state.player.data.get("duration", 0)
                dbg(f"_updater_loop: elapsed={elapsed} total={total}")
                # ! 메시지 수정(임베드, 뷰)
                embed = self._make_playing_embed(
                    state.player, guild_id, min(elapsed, total) if total else elapsed
                )
                await self._edit_msg(state, embed, state.control_view)
                await asyncio.sleep(5)
        finally:
            dbg("_updater_loop: end")
            state.updater_task = None

    def _cancel_idle_disconnect(self, state: GuildMusicState) -> None:
        task = state.idle_disconnect_task
        if task and not task.done():
            task.cancel()
        state.idle_disconnect_task = None

    def _schedule_idle_disconnect(self, guild_id: int) -> None:
        state = self._get_state(guild_id)
        self._cancel_idle_disconnect(state)
        task = self._spawn_bg(self._idle_disconnect_after_timeout(guild_id))
        state.idle_disconnect_task = task

        def _clear_task(done_task: asyncio.Task) -> None:
            if state.idle_disconnect_task is done_task:
                state.idle_disconnect_task = None

        task.add_done_callback(_clear_task)

    async def _idle_disconnect_after_timeout(self, guild_id: int):
        try:
            await asyncio.sleep(IDLE_DISCONNECT_SECONDS)
            state = self._get_state(guild_id)
            if state.player or state.queue:
                return

            guild = self.bot.get_guild(guild_id)
            voice_client = guild.voice_client if guild else None
            if voice_client:
                try:
                    await voice_client.disconnect()
                except Exception as e:
                    dbg(f"_idle_disconnect_after_timeout: disconnect 실패: {type(e)} {e}")

            state.control_view = await self._build_helper_view(guild_id)
            state.paused_at = None
            state.start_ts = 0.0
            state.is_loop = False
            state.is_skipping = False
            state.is_stopping = False
            try:
                await self._edit_msg(state, self._make_default_embed(), state.control_view)
            except Exception as e:
                dbg(f"_idle_disconnect_after_timeout: 패널 리셋 실패: {type(e)} {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            dbg(f"_idle_disconnect_after_timeout: failed: {type(e)} {e}")

    async def _force_stop(self, guild_id: int):
        """interaction 없이 강제 정지하고 패널을 초기 상태로 돌립니다."""
        dbg(f"_force_stop: guild_id={guild_id}")
        state = self._get_state(guild_id)
        self._cancel_idle_disconnect(state)
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client if guild else None
        # 정지 상태 진입
        state.is_stopping = True
        if vc:
            try:
                await vc.disconnect()
            except Exception as e:
                dbg(f"_force_stop: disconnect 실패: {type(e)} {e}")
        state.control_view = await self._build_helper_view(guild_id)
        embed = self._make_default_embed()
        try:
            await self._edit_msg(state, embed, state.control_view)
        except Exception as e:
            dbg(f"_force_stop: 패널 리셋 실패: {type(e)} {e}")
        # 상태 초기화
        state.player = None
        state.queue.clear()
        state.is_loop = False
        state.is_skipping = False
        if state.updater_task:
            state.updater_task.cancel()
            state.updater_task = None

    # ?완
    # ! 메시지 자동 삭제
    async def _auto_delete(self, msg: discord.Message, delay: float = 5.0):
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except discord.HTTPException:
            pass

    # ?완
    # ! 기본 임베드
    def _make_default_embed(self) -> Embed:
        try:
            # ! 임베드 기본 설정
            embed = Embed(
                title="🎵 신창섭의 다해줬잖아",
                description="명령어로 음악을 재생·일시정지·스킵할 수 있습니다.\n재생 이후 버튼을 통해 제어도 가능합니다.\n(재생 후 첫 대기열 추가 시 노래가 일시 끊길 수도 있습니다.)",
                color=0xFFC0CB,
                timestamp=datetime.now(),
            )
            # ! 도움말 섹션
            embed.add_field(
                name="❓ 사용법",
                value=(
                    "• `/재생 <URL/검색어>`: 유튜브 <URL/검색어>로 즉시 재생\n"
                    "• `/스킵`: 현재 재생중인 곡 스킵(다음 대기열 재생)\n"
                    "• `/대기열`: 현재 대기열 확인\n"
                    "• `/구간이동 <시간>`: 현재 곡의 위치 이동\n"
                    "• `/반복`: 현재 곡 반복 모드 토글\n"
                    "• `/대기열삭제 <번호>`, `/대기열비우기`, `/대기열이동`, `/셔플`: 대기열 관리\n"
                    "• `/일시정지`, 현재 재생중인 곡 일시정지\n"
                    "• `/다시재생`: 일시정지된 곡 다시재생\n"
                    "• `/정지`: 노래 종료 후 신창섭 퇴장\n\n"
                    "👉 재생시 생기는 버튼을 눌러도 동일 기능을 사용할 수 있습니다."
                ),
                inline=False,
            )
            # ! footer
            embed.set_footer(
                text="정상화 해줬잖아. 그냥 다 해줬잖아.",
                icon_url=self.bot.user.avatar.url,  # 봇 프로필 아이콘
            )
            return embed
        except Exception:
            logger.exception("기본 음악 패널 임베드 생성 실패")
            raise

    # ! 노래 재생시 임베드
    def _make_playing_embed(
        self, player: YTDLSource, guild_id: int, elapsed: int = 0
    ) -> Embed:
        try:
            total = player.data.get("duration", 0)
            # ! 임베드 기본 설정
            embed = Embed(title=PANEL_TITLE, color=0xFFC0CB)
            # ! 섬네일
            embed.set_thumbnail(url=player.data.get("thumbnail"))
            embed.add_field(name="곡 제목", value=player.title, inline=False)
            # ! 진행바 생성
            timeline = self.make_timeline_line(elapsed, total)
            bar, _ = self.make_progress_bar(elapsed, total)
            embed.add_field(name="진행", value=f"\n{timeline}\n`{bar}`", inline=False)
            # ! footer에 반복 상태
            state = self._get_state(guild_id)
            queue_preview = build_queue_preview(state.queue)
            if queue_preview:
                queue_title, queue_value = queue_preview
                embed.add_field(name=queue_title, value=queue_value, inline=False)
            requester = player.requester
            requester_name = requester.display_name if requester else UNKNOWN
            requester_icon = (
                requester.display_avatar.url if requester else self.bot.user.avatar.url
            )

            embed.set_footer(
                text=f"신청자: {requester_name} | 반복: {'켜짐' if state.is_loop else '꺼짐'} | {'⏸️ 일시정지 상태' if state.paused_at else '▶️ 재생중...'}",
                icon_url=requester_icon,
            )
            return embed
        except Exception:
            logger.exception("음악 재생 임베드 생성 실패")
            raise

    # ?완
    # ! 전용채널의 봇 댓글 가져오거나 생성
    async def _get_or_create_panel(self, guild: discord.Guild):
        # ! 상태 기본값 설정
        state = self._get_state(guild.id)
        # ! 채널 확보
        control_channel = await self._resolve_music_channel(guild)
        # ! 채널 없으면 생성
        if control_channel is None:
            print("[채널 없음]->", end="")
            # ! 권한 설정
            bot_member = guild.get_member(self.bot.user.id)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(send_messages=True),
                bot_member: discord.PermissionOverwrite(
                    send_messages=True, embed_links=True, read_messages=True
                ),
            }
            control_channel = await guild.create_text_channel(
                DEFAULT_MUSIC_CHANNEL_NAME,
                overwrites=overwrites,
            )
            print("[채널 생성됨]")

        # ! 상태 업데이트, 기본 임베드 뷰 생성
        print("[길드 상태 업데이트, 기본 임베드 뷰 생성]")
        embed = self._make_default_embed()
        state.control_channel = control_channel
        state.control_view = await self._build_helper_view(guild.id)

        # 1) 저장된 ID 우선 시도
        fetched = False
        gid_key = str(guild.id)
        stored_id = self._panel_ids.get(gid_key)
        if stored_id:
            try:
                control_msg = await control_channel.fetch_message(stored_id)
                if (
                    control_msg
                    and control_msg.author == guild.me
                    and control_msg.embeds
                ):
                    em = control_msg.embeds[0]
                    if em.title in (PANEL_TITLE, embed.title):
                        print("[저장된 패널 메시지 재사용]")
                        state.control_msg = control_msg
                        await self._edit_msg(state, embed, state.control_view)
                        fetched = True
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.info("저장된 패널 ID fetch 실패 -> fallback", exc_info=True)
                # 실패 시 dict에서 제거
                await self._del_panel_id(gid_key)

        if not fetched:
            # 2) 히스토리 스캔
            async for control_msg in control_channel.history(limit=50):
                if control_msg.author == guild.me and control_msg.embeds:
                    em = control_msg.embeds[0]
                    if em.title == PANEL_TITLE:
                        print("[기존 임베드 발견]")
                        state.control_msg = control_msg
                        # 발견 즉시 ID 저장
                        await self._set_panel_id(gid_key, control_msg.id)
                        await self._edit_msg(state, embed, state.control_view)
                        fetched = True
                        break

        if fetched:
            return

        # ! 없으면 새로 보내기
        print("[기존 메시지 없음] -> 전송")
        state.control_msg = await control_channel.send(
            embed=embed, view=state.control_view
        )
        self._panel_ids[gid_key] = state.control_msg.id
        await self._set_panel_id(gid_key, state.control_msg.id)

    # === 부팅 직후 음악 채널 정리 ===
    async def _purge_music_channel_extras(self, guild: discord.Guild, limit: int = 500):
        """음악 채널에서 '패널 임베드' 메시지를 제외한 일반 사용자/과거 메세지를 정리.

        조건:
        - 채널명: DEFAULT_MUSIC_CHANNEL_NAME 또는 /채널설정 기능:음악 대상
        - 유지: 봇이 보낸 패널 메시지(제목이 PANEL_TITLE 또는 기본 패널 제목)
        - 나머지: 모두 삭제 (핀 고정은 존중 -> pinned True면 건너뜀)
        - 1회만 수행 (재연결 시 중복 제거 방지)
        """
        if guild.id in self._purged_guilds:
            return
        state = self._get_state(guild.id)
        channel = state.control_channel or await self._resolve_music_channel(guild)
        if channel is None:
            return
        panel_msg_id = (
            state.control_msg.id
            if state.control_msg
            else self._panel_ids.get(str(guild.id))
        )
        kept_ids = {panel_msg_id} if panel_msg_id else set()
        removed = 0
        try:
            async for msg in channel.history(limit=limit, oldest_first=False):
                if msg.pinned:
                    continue
                if kept_ids and msg.id in kept_ids:
                    continue
                # 패널 메시지 판별(혹시 id 저장 실패 케이스 대비)
                if (
                    msg.author == guild.me
                    and msg.embeds
                    and msg.embeds[0].title in (PANEL_TITLE, "🎵 신창섭의 다해줬잖아")
                ):
                    # 패널로 간주하고 ID 업데이트 후 유지
                    if not kept_ids:
                        kept_ids.add(msg.id)
                    continue
                try:
                    await msg.delete()
                    removed += 1
                except discord.HTTPException:
                    continue
        finally:
            if removed:
                dbg(f"_purge_music_channel_extras: guild={guild.id} removed={removed}")
            self._purged_guilds.add(guild.id)

    # ?완
    # !노래 재생 or 대기열
    async def _play_url_now(
        self,
        interaction: discord.Interaction,
        url: str,
        *,
        success_prefix: str = "▶ 재생",
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)

        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        voice_client = interaction.guild.voice_client
        user_channel = self._user_voice_channel(interaction)

        if not voice_client:
            if not user_channel:
                await self._send_auto_delete(
                    interaction,
                    "❌ 먼저 음성 채널에 들어가 있어야 합니다.",
                )
                return
            voice_client = await user_channel.connect()
            dbg(f"_play_url_now: connected to voice channel id={user_channel.id}")
        elif user_channel and voice_client.channel != user_channel:
            if voice_client.is_playing() or voice_client.is_paused():
                await self._send_auto_delete(
                    interaction,
                    "❌ 같은 음성 채널에 있는 사용자만 음악을 제어할 수 있습니다.",
                )
                return
            await voice_client.move_to(user_channel)
        elif not user_channel:
            await self._send_auto_delete(
                interaction,
                "❌ 먼저 음성 채널에 들어가 있어야 합니다.",
            )
            return

        try:
            player = await YTDLSource.from_url(
                url,
                loop=self.bot.loop,
                requester=interaction.user,
            )
        except FileNotFoundError:
            await self._send_auto_delete(
                interaction,
                "❌ FFmpeg 실행 파일을 찾을 수 없습니다.",
                delay=8.0,
            )
            return
        except Exception as e:
            dbg(f"_play_url_now: 소스 준비 실패: {type(e)} {e}")
            await self._send_auto_delete(
                interaction,
                "❌ 스트림 URL을 가져오지 못했습니다. 잠시 후 다시 시도하거나 다른 영상으로 시도해 주세요.",
                delay=10.0,
            )
            return

        replacing = bool(
            voice_client and (voice_client.is_playing() or voice_client.is_paused())
        )
        state.is_stopping = False
        state.is_skipping = False
        if replacing:
            state.is_seeking = True
            voice_client.stop()

        try:
            self._cancel_idle_disconnect(state)
            state.player = player
            state.start_ts = time.time()
            state.paused_at = None
            state.control_view = await self._build_control_view(guild_id, state)
            self._vc_play(guild_id=guild_id, source=player.source)
            await self._restart_updater(guild_id)
            embed = self._make_playing_embed(player, guild_id)
            await self._edit_msg(state=state, embed=embed, view=state.control_view)
        finally:
            if replacing:
                state.is_seeking = False

        msg = await interaction.followup.send(
            f"{success_prefix}: **{player.title}**",
            ephemeral=True,
        )
        self._spawn_bg(self._auto_delete(msg, 5.0))

    async def _play(self, interaction, url: str, skip_defer: bool = False):
        dbg(
            f"_play: called url={url} guild={interaction.guild.id} user={interaction.user.id}"
        )
        # ? 검색어 처리
        if not re.match(r"^https?://", url):
            # ytsearch로 상위 10개까지 뽑되
            info = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: search_ytdl.extract_info(f"ytsearch10:{url}", download=False),
            )
            dbg(
                f"_play: search info keys={list(info.keys()) if isinstance(info,dict) else type(info)}"
            )
            raw = info.get("entries", []) or []
            dbg(f"_play: raw entries count={len(raw)}")
            # 유효한 영상 URL만 필터
            videos = [
                e
                for e in raw
                if isinstance(e.get("url"), str) and "watch?v=" in e["url"]
            ][:10]
            if not videos:
                return await interaction.response.send_message(
                    "❌ 검색 결과가 없습니다.", ephemeral=True
                )

            dbg(f"_play: videos_count={len(videos)}")

            # Embed  View 생성
            description = "\n".join(
                f"{i+1}. {v.get('title','-')}" for i, v in enumerate(videos)
            )
            dbg(f"_play: description built length={len(description)}")
            embed = Embed(
                title=f"🔍 `{url}` 검색 결과",
                description=description,
                color=0xFFC0CB,
            )
            view = SearchResultView(self, videos)
            # ! 완료 메시지
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        embed=embed, view=view, ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        embed=embed, view=view, ephemeral=True
                    )
            except Exception as e:
                dbg(f"_play: interaction response failed: {type(e)} {e}")
            # 검색 모드에서는 여기서 종료 (선택은 SelectView가 처리)
            return

        # ? URL 재생
        if not skip_defer:
            await interaction.response.defer(thinking=True, ephemeral=True)

        # ! 기본정보 로드
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client
        user_channel = self._user_voice_channel(interaction)

        # ! 봇이 음성 채널에 없음
        if not voice_client:
            # ! 유저가 음성채널에 없음
            if not user_channel:
                return await interaction.followup.send(
                    "❌ 먼저 음성 채널에 들어가 있어야 합니다.", ephemeral=True
                )
            # ! 봇을 채널 연결
            voice_client = await user_channel.connect()
            dbg(f"_play: connected to voice channel id={user_channel.id}")
        elif user_channel and voice_client.channel != user_channel:
            if voice_client.is_playing() or voice_client.is_paused():
                msg = await interaction.followup.send(
                    "❌ 같은 음성 채널에 있는 사용자만 음악을 추가할 수 있습니다.",
                    ephemeral=True,
                )
                self._spawn_bg(self._auto_delete(msg, 5.0))
                return
            await voice_client.move_to(user_channel)
            dbg(f"_play: moved to voice channel id={user_channel.id}")
        elif not user_channel:
            msg = await interaction.followup.send(
                "❌ 먼저 음성 채널에 들어가 있어야 합니다.", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return

        # ! 이미 재생(또는 일시정지) 중이면 URL만 큐에 추가
        state = self._get_state(interaction.guild.id)
        self._cancel_idle_disconnect(state)
        if (voice_client and voice_client.is_playing()) or (
            voice_client and voice_client.is_paused()
        ):
            track = QueuedTrack(url=url, requester=interaction.user)
            state.queue.append(track)
            dbg(f"_play: appended URL to queue size={len(state.queue)}")
            # 메타데이터는 백그라운드에서 채움(가벼운 작업으로 유지)
            self._spawn_bg(self._fill_queue_meta(track))
            # ! 완료 메시지
            msg = await interaction.followup.send(
                "▶ **대기열에 추가되었습니다.**", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return

        # ! 재생 중이 아니면 지금 URL로 바로 준비 후 재생
        try:
            player = await YTDLSource.from_url(
                url, loop=self.bot.loop, requester=interaction.user
            )
            dbg(f"_play: prepared player title={getattr(player,'title',None)}")
        except FileNotFoundError:
            msg = await interaction.followup.send(
                "❌ FFmpeg 실행 파일을 찾을 수 없습니다.\n- bin/ffmpeg.exe를 다운로드해 배치하거나,\n- ffmpeg를 시스템 PATH에 추가한 뒤 다시 시도해 주세요.",
                ephemeral=True,
            )
            self._spawn_bg(self._auto_delete(msg, 12.0))
            dbg("_play: ffmpeg not found")
            return
        except Exception as e:
            dbg(f"_play: 소스 준비 실패: {type(e)} {e}")
            msg = await interaction.followup.send(
                "❌ 스트림 URL을 가져오지 못했습니다. 잠시 후 다시 시도하거나 다른 영상으로 시도해 주세요.",
                ephemeral=True,
            )
            self._spawn_bg(self._auto_delete(msg, 10.0))
            return

        # !상태 업데이트 및 재생 시작
        state.is_stopping = False
        state.is_skipping = False
        state.player = player
        state.start_ts = time.time()
        state.paused_at = None
        self._vc_play(guild_id=guild_id, source=player.source)
        await self._restart_updater(guild_id)
        dbg("_play: playback started and updater restarted")
        embed = self._make_playing_embed(player, guild_id)
        state.control_view = await self._build_control_view(guild_id, state)
        await self._edit_msg(state=state, embed=embed, view=state.control_view)
        msg = await interaction.followup.send(
            f"▶ 재생: **{player.title}**", ephemeral=True
        )
        self._spawn_bg(self._auto_delete(msg, 5.0))

    async def _pause(self, interaction):
        # !기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        voice_client = interaction.guild.voice_client
        # !재생중 아님
        if not voice_client or not voice_client.is_playing():
            msg = await interaction.followup.send(MSG_NO_PLAYING, ephemeral=True)
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return
        if error := self._same_voice_channel_error(interaction, voice_client):
            msg = await interaction.followup.send(error, ephemeral=True)
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return
        print("[일시정지]")
        voice_client.pause()
        # !상태설정
        state.paused_at = time.time()
        # ! embed 업데이트
        elapsed = int(time.time() - state.start_ts)
        embed = self._make_playing_embed(state.player, guild_id, elapsed)
        # ! view 재생성
        state.control_view = await self._build_control_view(guild_id, state)
        await self._edit_msg(state, embed, state.control_view)
        # !메시지
        self._spawn_bg(
            self._auto_delete(
                await interaction.followup.send("⏸️ 일시정지했습니다.", ephemeral=True),
                5.0,
            )
        )

    async def _resume(self, interaction):
        # !기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        voice_client = interaction.guild.voice_client
        try:
            # !재생중 아님
            if not voice_client or not voice_client.is_paused():
                msg = await interaction.followup.send(
                    "❌ 일시정지된 음악이 없습니다.", ephemeral=True
                )
                self._spawn_bg(self._auto_delete(msg, 5.0))
                return
            if error := self._same_voice_channel_error(interaction, voice_client):
                msg = await interaction.followup.send(error, ephemeral=True)
                self._spawn_bg(self._auto_delete(msg, 5.0))
                return
            print("[다시재생]")
            voice_client.resume()
            # !상태설정
            if state.paused_at:
                delta = time.time() - state.paused_at
                state.start_ts += delta
                state.paused_at = None
            # ! embed 업데이트
            elapsed = int(time.time() - state.start_ts)
            embed = self._make_playing_embed(state.player, guild_id, elapsed)
            # ! view 재생성
            state.control_view = await self._build_control_view(guild_id, state)
            await self._edit_msg(state, embed, state.control_view)
            # !메시지
            self._spawn_bg(
                self._auto_delete(
                    await interaction.followup.send(
                        "▶️ 다시 재생합니다.", ephemeral=True
                    ),
                    5.0,
                )
            )
        except Exception as e:
            dbg(f"_resume: failed: {type(e)} {e}")
            msg = await interaction.followup.send(
                "❌ 다시 재생 중 오류가 발생했습니다.", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 5.0))

    async def _skip(self, interaction: discord.Interaction):
        print("[스킵]")
        # ! 기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            msg = await interaction.followup.send(MSG_NO_PLAYING, ephemeral=True)
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return
        if error := self._same_voice_channel_error(interaction, voice_client):
            msg = await interaction.followup.send(error, ephemeral=True)
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return

        if state.is_loop:
            # ! 현재 트랙 강제 중단
            state.is_skipping = True
            voice_client.stop()
            state.is_skipping = False
            msg_text = "🔁 반복 모드: 처음부터 재생합니다."
        else:
            # ! queue나 다음 트랙 로직은 on_song_end에 맡김
            voice_client.stop()
            msg_text = "⏭️ 스킵합니다."

        # !메시지
        msg = await interaction.followup.send(msg_text, ephemeral=True)
        self._spawn_bg(self._auto_delete(msg, 5.0))

    async def _stop(self, interaction: discord.Interaction):
        print("[정지]")
        await interaction.response.defer(thinking=True, ephemeral=True)
        state = self._get_state(interaction.guild.id)
        voice_client = interaction.guild.voice_client
        if not voice_client:
            msg = await interaction.followup.send(
                "❌ 봇이 음성채널에 없습니다.", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return
        if error := self._same_voice_channel_error(interaction, voice_client):
            msg = await interaction.followup.send(error, ephemeral=True)
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return
        # 정지 상태 진입
        state.is_stopping = True
        await voice_client.disconnect()

        # ! reset panel
        state.control_view = await self._build_helper_view(interaction.guild.id)
        embed = self._make_default_embed()
        await self._edit_msg(state, embed, state.control_view)

        # ! 재생 상태 완전 초기화
        state.player = None
        state.queue.clear()
        state.is_loop = False
        state.is_skipping = False
        if state.updater_task:
            state.updater_task.cancel()
            state.updater_task = None

        # ! 메시지
        self._spawn_bg(
            self._auto_delete(
                await interaction.followup.send(
                    "⏹️ 정지하고 나갑니다.", ephemeral=True
                ),
                5.0,
            )
        )

    async def _show_queue(self, interaction: discord.Interaction):
        print("[대기열보기]")
        await interaction.response.defer(thinking=True, ephemeral=True)
        state = self._get_state(interaction.guild.id)
        if not state.queue:
            msg = await interaction.followup.send(
                "❌ 대기열이 비어있습니다.", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return

        n = len(state.queue)
        # !재생 중 정보
        desc_lines = []
        if state.player and state.player.title:
            total = state.player.data.get("duration", 0)
            m, s = divmod(total, 60)
            uploader = state.player.data.get("uploader") or UNKNOWN
            user = (
                f"<@{state.player.requester.id}>" if state.player.requester else UNKNOWN
            )
            desc_lines.append(
                f"**현재 재생 중.** \n"
                f"[{state.player.title}]({state.player.webpage_url})({m:02}:{s:02})"
                f"({uploader}) - 신청자: {user}"
            )
            desc_lines.append("")  # 구분선 역할

        # 대기열 리스트 (URL 기반 QueuedTrack)
        visible_tracks = list(state.queue)[:MAX_QUEUE_DISPLAY]
        for i, track in enumerate(visible_tracks, start=1):
            total = track.duration or 0
            m, s = divmod(total, 60)
            uploader = track.uploader or UNKNOWN
            user = f"<@{track.requester.id}>" if track.requester else UNKNOWN
            title = _track_title(track)
            link = track.webpage_url or track.url
            length = f"({m:02}:{s:02})" if total else ""
            desc_lines.append(
                f"{i}. [{title}]({link}){length}({uploader}) - 신청자: {user}"
            )
        if len(state.queue) > MAX_QUEUE_DISPLAY:
            desc_lines.append(f"... 외 {len(state.queue) - MAX_QUEUE_DISPLAY}곡")

        embed = Embed(
            title=f"대기열 - {n}개의 곡",
            description="\n".join(desc_lines),
            color=0xFFC0CB,
        )

        msg = await interaction.followup.send(embed=embed, ephemeral=True)
        self._spawn_bg(self._auto_delete(msg, 20.0))

    async def _remove_from_queue(
        self, interaction: discord.Interaction, position: int
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        voice_client = interaction.guild.voice_client
        if voice_client and (error := self._same_voice_channel_error(interaction, voice_client)):
            await self._send_auto_delete(interaction, error)
            return

        state = self._get_state(interaction.guild.id)
        if not state.queue:
            await self._send_auto_delete(interaction, "❌ 대기열이 비어있습니다.")
            return
        try:
            removed = remove_queue_track(state.queue, position)
        except ValueError as e:
            await self._send_auto_delete(interaction, f"❌ {e}")
            return
        await self._send_auto_delete(
            interaction, f"🗑️ 대기열에서 **{_track_title(removed)}** 항목을 삭제했습니다."
        )

    async def _clear_queue(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        voice_client = interaction.guild.voice_client
        if voice_client and (error := self._same_voice_channel_error(interaction, voice_client)):
            await self._send_auto_delete(interaction, error)
            return

        state = self._get_state(interaction.guild.id)
        count = len(state.queue)
        if count == 0:
            await self._send_auto_delete(interaction, "❌ 대기열이 비어있습니다.")
            return
        state.queue.clear()
        await self._send_auto_delete(interaction, f"🧹 대기열 {count}곡을 비웠습니다.")

    async def _move_queue(
        self, interaction: discord.Interaction, current_position: int, new_position: int
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        voice_client = interaction.guild.voice_client
        if voice_client and (error := self._same_voice_channel_error(interaction, voice_client)):
            await self._send_auto_delete(interaction, error)
            return

        state = self._get_state(interaction.guild.id)
        if not state.queue:
            await self._send_auto_delete(interaction, "❌ 대기열이 비어있습니다.")
            return
        try:
            moved = move_queue_track(state.queue, current_position, new_position)
        except ValueError as e:
            await self._send_auto_delete(interaction, f"❌ {e}")
            return
        await self._send_auto_delete(
            interaction,
            f"↕️ **{_track_title(moved)}** 항목을 {new_position}번으로 이동했습니다.",
        )

    async def _shuffle_queue(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        voice_client = interaction.guild.voice_client
        if voice_client and (error := self._same_voice_channel_error(interaction, voice_client)):
            await self._send_auto_delete(interaction, error)
            return

        state = self._get_state(interaction.guild.id)
        if len(state.queue) < 2:
            await self._send_auto_delete(
                interaction, "❌ 섞을 대기열이 2곡 이상 필요합니다."
            )
            return
        shuffle_queue(state.queue)
        await self._send_auto_delete(interaction, "🔀 대기열을 섞었습니다.")

    async def _restart_updater(self, guild_id: int):
        dbg("_restart_updater: called")
        # ! 기본정보 로드
        state = self._get_state(guild_id)

        # ! task 종료
        if state.updater_task:
            dbg("_restart_updater: cancel existing updater_task")
            state.updater_task.cancel()

        # ! task 종료 대기
        while state.updater_task:
            dbg("_restart_updater: waiting for updater_task to finish")
            await asyncio.sleep(0.5)

        # ! task 재등록
        dbg("_restart_updater: creating new updater task")
        state.updater_task = self._spawn_bg(self._updater_loop(guild_id))
        await asyncio.sleep(1)

    async def _seek(self, interaction: discord.Interaction, seconds: int):
        dbg(f"_seek: seconds={seconds}")
        # ! 기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        voice_client = interaction.guild.voice_client
        if not voice_client or not state.player:
            # ! 메시지
            msg = await interaction.followup.send(MSG_NO_PLAYING, ephemeral=True)
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return
        if error := self._same_voice_channel_error(interaction, voice_client):
            msg = await interaction.followup.send(error, ephemeral=True)
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return
        try:
            total = int(state.player.data.get("duration", 0) or 0)
            if total and seconds >= total:
                msg = await interaction.followup.send(
                    f"❌ 이동할 시간은 곡 길이({total}초)보다 작아야 합니다.",
                    ephemeral=True,
                )
                self._spawn_bg(self._auto_delete(msg, 6.0))
                return
            # ! 새로운 player 생성 (start_time 포함)
            player = await YTDLSource.from_url(
                url=state.player.webpage_url,
                loop=self.bot.loop,
                start_time=seconds,
                requester=state.player.requester,
            )
            # ! 멈추고 재생 위치부터 새 소스 생성
            state.is_seeking = True
            voice_client.stop()
            dbg("_seek: stopped current and will restart from position")
            state.player = player
            state.start_ts = time.time() - seconds
            state.paused_at = None
            # ! play & updater 재시작
            self._vc_play(guild_id=guild_id, source=player.source)
            await self._restart_updater(guild_id)
            # ! 메시지 수정(임베드, 뷰)
            embed = self._make_playing_embed(state.player, guild_id, elapsed=seconds)
            await self._edit_msg(state, embed, state.control_view)
            # ! seek 끝
            state.is_seeking = False
            # ! 메시지
            msg = await interaction.followup.send(
                f"⏩ {seconds}초 지점으로 이동했습니다.", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 5.0))
        except FileNotFoundError:
            msg = await interaction.followup.send(
                "❌ FFmpeg 실행 파일을 찾을 수 없습니다.", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 8.0))
            state.is_seeking = False
        except Exception as e:
            dbg(f"_seek: failed: {type(e)} {e}")
            # 실패 시 is_seeking 안전 복구
            state.is_seeking = False
            msg = await interaction.followup.send(
                "❌ 구간 이동 중 오류가 발생했습니다.", ephemeral=True
            )
            self._spawn_bg(self._auto_delete(msg, 6.0))

    # ?완료
    async def _toggle_loop(self, interaction: discord.Interaction):
        """🔁 반복 모드 토글"""
        await interaction.response.defer(thinking=True, ephemeral=True)
        # ! 상태 업데이트
        state = self._get_state(interaction.guild.id)
        voice_client = interaction.guild.voice_client
        if voice_client and (error := self._same_voice_channel_error(interaction, voice_client)):
            msg = await interaction.followup.send(error, ephemeral=True)
            self._spawn_bg(self._auto_delete(msg, 5.0))
            return
        state.is_loop = not state.is_loop
        # ! 메시지
        msg = await interaction.followup.send(
            f"🔁 반복 모드 {'켜짐' if state.is_loop else '꺼짐'}", ephemeral=True
        )
        self._spawn_bg(self._auto_delete(msg, 5.0))

    # ?완료
    def _vc_play(
        self, guild_id: int = None, interaction: discord.Interaction = None, source=None
    ):
        # ! 재생 및 다음 곡 콜백 등록
        def _after_play(error):
            if error:
                dbg(f"_after_play: error={error}")
            else:
                dbg("_after_play: finished")

            def _schedule_song_end() -> None:
                self._spawn_bg(self._on_song_end(guild_id))

            self.bot.loop.call_soon_threadsafe(_schedule_song_end)

        # ! voice_client 가져오기
        if guild_id:
            guild = self.bot.get_guild(guild_id)
            voice_client = guild.voice_client
        else:
            voice_client = interaction.guild.voice_client

        # ! 재생
        try:
            dbg("_vc_play: voice_client.play invoked")
            voice_client.play(source, after=_after_play)
        except discord.errors.ClientException:
            dbg("_vc_play: ClientException -> stop then play")
            voice_client.stop()
            voice_client.play(source, after=_after_play)

    async def _on_song_end(self, guild_id: int):
        dbg("_on_song_end: called")
        # ! 기본정보 로드
        state = self._get_state(guild_id)

        # 정지 상태면 아무 것도 하지 않음
        if state.is_stopping:
            dbg("_on_song_end: stopping flag set -> return")
            state.is_stopping = False
            return

        # ! seek 발생시 종료 로직 무시
        if state.is_seeking:
            dbg("_on_song_end: in seeking, ignore")
            return

        # ! task 종료, 상태 업데이트
        if state.updater_task:
            state.updater_task.cancel()
        state.paused_at = None
        state.start_ts = time.time()

        # !루프이거나 루프상태인데 스킵하면 처음부터
        if state.is_skipping or state.is_loop:
            dbg(f"_on_song_end: loop/skip replay queue_size={len(state.queue)}")
            ffmpeg_exec = _detect_ffmpeg_executable()
            try:
                audio_url = getattr(
                    state.player, "audio_url", None
                ) or state.player.data.get("url")
                new_source = discord.FFmpegOpusAudio(
                    audio_url, **ffmpeg_options, executable=ffmpeg_exec
                )
            except Exception as e:
                dbg(f"_on_song_end: reuse url failed -> refresh: {type(e)} {e}")
                try:
                    refreshed = await YTDLSource.from_url(
                        state.player.webpage_url, loop=self.bot.loop
                    )
                    state.player.audio_url = refreshed.audio_url
                    new_source = refreshed.source
                except Exception as e2:
                    dbg(f"_on_song_end: refresh failed: {type(e2)} {e2}")
                    await self._force_stop(guild_id)
                    return
            # ! 상태 업데이트
            state.player.source = new_source
            # ! play & updater 재시작
            self._vc_play(guild_id, source=new_source)
            await self._restart_updater(guild_id)
            return

        # !대기열에 곡이 없으면 패널을 빈(embed 초기) 상태로 리셋
        if not state.queue:
            dbg("_on_song_end: no next track -> reset panel and wait for idle timeout")
            state.player = None
            state.paused_at = None
            state.start_ts = 0.0
            state.control_view = await self._build_helper_view(guild_id)
            await self._edit_msg(state, self._make_default_embed(), state.control_view)
            self._schedule_idle_disconnect(guild_id)
            return

        # ! 다음 곡 준비: URL -> YTDLSource 변환 후 재생
        dbg(f"_on_song_end: next track popped, queue_size={len(state.queue)}")
        track = state.queue.popleft()
        try:
            player = await YTDLSource.from_url(
                track.url, loop=self.bot.loop, requester=track.requester
            )
        except Exception as e:
            dbg(f"_on_song_end: next track prepare failed: {type(e)} {e}")
            # 실패 시 다음 곡으로 넘어가기 시도 (재귀적 호출 방지 위해 task로)
            self._spawn_bg(self._on_song_end(guild_id))
            return
        self._cancel_idle_disconnect(state)
        state.player = player
        state.start_ts = time.time()
        state.paused_at = None
        embed = self._make_playing_embed(state.player, guild_id)
        await self._edit_msg(state, embed, state.control_view)
        self._vc_play(guild_id, source=state.player.source)
        await self._restart_updater(guild_id)

    @app_commands.command(
        name="음악", description="음악 재생 상태와 컨트롤 버튼을 보여줍니다."
    )
    async def 음악(self, interaction: discord.Interaction):
        print("[음악] 명령 시작")
        # !메시지
        await interaction.response.send_message(
            "음악 컨트롤 패널을 설정 중입니다…", ephemeral=True
        )
        # !길드별 State 초기화
        await self._get_or_create_panel(interaction.guild)
        print(f"[음악] Panel updated in 길드: {interaction.guild}")

    @app_commands.command(name="재생", description="유튜브 URL을 재생합니다.")
    @app_commands.rename(url="검색어")
    @app_commands.describe(url="재생할 유튜브 URL 혹은 검색어")
    async def 재생(self, interaction: discord.Interaction, url: str):
        await self._play(interaction, url)

    @app_commands.command(name="일시정지", description="음악 일시정지")
    async def 일시정지(self, interaction: discord.Interaction):
        await self._pause(interaction)

    @app_commands.command(name="다시재생", description="일시정지된 음악 재생")
    async def 다시재생(self, interaction: discord.Interaction):
        await self._resume(interaction)

    @app_commands.command(name="정지", description="음악 정지 및 퇴장")
    async def 정지(self, interaction: discord.Interaction):
        await self._stop(interaction)

    @app_commands.command(name="스킵", description="현재 재생 중인 곡을 넘깁니다.")
    async def 스킵(self, interaction: discord.Interaction):
        await self._skip(interaction)

    @app_commands.command(name="대기열", description="현재 음악 대기열을 보여줍니다.")
    async def 대기열(self, interaction: discord.Interaction):
        await self._show_queue(interaction)

    @app_commands.command(name="구간이동", description="현재 곡의 재생 위치를 이동합니다.")
    @app_commands.describe(시간="이동할 시간. 예: 1:23 또는 83")
    async def 구간이동(self, interaction: discord.Interaction, 시간: str):
        try:
            seconds = parse_seek_seconds(시간)
        except ValueError:
            await interaction.response.send_message(
                "❌ 시간 형식이 올바르지 않습니다. 예: 1:23 또는 83",
                ephemeral=True,
            )
            return
        await self._seek(interaction, seconds)

    @app_commands.command(name="반복", description="현재 곡 반복 모드를 켜거나 끕니다.")
    async def 반복(self, interaction: discord.Interaction):
        await self._toggle_loop(interaction)

    @app_commands.command(name="대기열삭제", description="대기열에서 지정한 번호의 곡을 삭제합니다.")
    @app_commands.describe(번호="삭제할 대기열 번호")
    async def 대기열삭제(self, interaction: discord.Interaction, 번호: int):
        await self._remove_from_queue(interaction, 번호)

    @app_commands.command(name="대기열비우기", description="현재 대기열을 모두 비웁니다.")
    async def 대기열비우기(self, interaction: discord.Interaction):
        await self._clear_queue(interaction)

    @app_commands.command(name="대기열이동", description="대기열 곡의 위치를 변경합니다.")
    @app_commands.describe(현재번호="현재 대기열 번호", 새번호="옮길 대기열 번호")
    async def 대기열이동(
        self,
        interaction: discord.Interaction,
        현재번호: int,
        새번호: int,
    ):
        await self._move_queue(interaction, 현재번호, 새번호)

    @app_commands.command(name="셔플", description="현재 대기열 순서를 무작위로 섞습니다.")
    async def 셔플(self, interaction: discord.Interaction):
        await self._shuffle_queue(interaction)

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> Music Cog : on ready!")
        # ! 모든 길드의 패널 설정
        for guild in self.bot.guilds:
            try:
                print("[on_ready] 길드 음악 상태 로드:", guild)
                await self._get_or_create_panel(guild)
                # 패널 확보 후 불필요 메세지 정리
                await self._purge_music_channel_extras(guild)
            except Exception:
                logger.exception("[on_ready] 길드 %s 패널 생성 실패", guild.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """음악 전용 채널에서 일반 유저 메시지를 자동 삭제.

        - 채널명: DEFAULT_MUSIC_CHANNEL_NAME 또는 /채널설정 기능:음악 대상
        - 봇 메시지는 허용
        - 패널/컨트롤 유지
        - Slash 명령은 별도의 application interaction이라 일반 메시지 객체가 아니므로 별도 처리 불필요
        """
        # DM / 시스템 / 웹훅 제외
        if not message.guild or message.type != discord.MessageType.default:
            return
        if message.author.bot:
            return
        if not await self._is_music_control_channel(message):
            return
        # 유저가 붙여넣은 일반 텍스트/URL 등 모두 삭제
        try:
            await message.delete()
        except discord.HTTPException:
            return
        # 경고 메시지 (쿨다운 내 중복 표시 방지)
        now = time.time()
        last = self._last_warn.get(message.author.id, 0)
        if now - last < self._warn_cooldown:
            return
        self._last_warn[message.author.id] = now
        try:
            warn_msg = await message.channel.send(
                f"{message.author.mention} 이 채널은 음악 명령 전용입니다. 다른 대화는 다른 채널을 이용해주세요!"
            )
            # 5초 후 자동 삭제
            self._spawn_bg(self._auto_delete(warn_msg, 5.0))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("음악 전용 채널 경고 메시지 전송 실패", exc_info=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, discord.errors.ClientException):
            return
        logger.exception("music command error", exc_info=(type(error), error, error.__traceback__))


async def setup(bot: commands.Bot):
    cog = MusicCog(bot)
    await bot.add_cog(cog)
    bot.add_view(MusicHelperView(cog))
    print("Music Cog : setup 완료!")
