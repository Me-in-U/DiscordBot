import asyncio
import logging
import os
import subprocess

import aiohttp
from yt_dlp.utils import DownloadError

from api.chatGPT import OpenAIModelError
from func.youtube_api import YouTubeApiError, fetch_youtube_comments, is_live_video
from func.youtube_links import (
    YOUTUBE_POST_KIND,
    extract_video_id,
    get_youtube_link_kind,
    normalize_youtube_link,
)
from func.youtube_media import (
    HEADERS,
    download_youtube_subtitles,
    speech_to_text,
    youtube_to_mp3,
)
from func.youtube_post import YouTubePostInfo, parse_youtube_post_html
from func.youtube_summarizer import (
    summarize_comments_with_gpt,
    summarize_text_with_gpt,
    summarize_youtube_post_with_gpt,
)
from func.youtube_transcript import read_subtitles_file
from func.youtube_workspace import youtube_audio_path, youtube_summary_workspace

logger = logging.getLogger(__name__)


class YouTubeSummaryError(Exception):
    """Raised when a YouTube summary request cannot be completed safely."""


async def fetch_youtube_post(url: str) -> YouTubePostInfo:
    normalized_url = normalize_youtube_link(url)
    async with aiohttp.ClientSession(headers=HEADERS, trust_env=False) as session:
        async with session.get(normalized_url) as response:
            response.raise_for_status()
            html = await response.text()

    return await asyncio.to_thread(parse_youtube_post_html, html, normalized_url)


async def process_youtube_post_link(url: str) -> str:
    post_info = await fetch_youtube_post(url)
    if not post_info.text and not post_info.attachment_urls:
        raise ValueError("게시물 본문을 추출하지 못했습니다.")

    return await summarize_youtube_post_with_gpt(post_info)


async def process_youtube_video_link(url: str) -> str:
    """
    1) 자막 다운로드 (한글 -> 영어) -> 2) (자막 없으면) MP3/STT -> 3) GPT 요약
    """
    summary_text = ""
    with youtube_summary_workspace() as workspace:
        mp3_path = str(youtube_audio_path(workspace))
        try:
            video_id = extract_video_id(url)
            if not video_id:
                raise ValueError("영상 ID를 추출하지 못했습니다.")

            if await asyncio.to_thread(is_live_video, video_id):
                raise ValueError("라이브(또는 예정) 방송은 요약을 진행할 수 없습니다.")

            subtitle_path = await asyncio.to_thread(
                download_youtube_subtitles,
                url,
                primary_lang="ko",
                fallback_lang="en",
                output_dir=workspace,
            )

            if subtitle_path:
                logger.debug("자막이 확인되었습니다. 자막을 사용합니다.")
                subtitles_text = await asyncio.to_thread(read_subtitles_file, subtitle_path)
                if not subtitles_text.strip():
                    logger.debug("자막 파일이 비어 있습니다. STT로 진행합니다.")
                    raise ValueError("자막 파일이 비어 있습니다.")
                summary_text = await summarize_text_with_gpt(subtitles_text)
            else:
                logger.debug("자막이 없습니다. STT를 진행합니다.")
                await youtube_to_mp3(url, output_path=mp3_path)
                stt_text = await speech_to_text(mp3_path)
                summary_text = await summarize_text_with_gpt(stt_text)

            video_id = extract_video_id(url)
            if video_id:
                try:
                    comments = await asyncio.to_thread(
                        fetch_youtube_comments, video_id, max_comments=40
                    )
                except YouTubeApiError:
                    logger.warning("YouTube 댓글 조회 실패: video_id=%s", video_id, exc_info=True)
                    comments = []
                if comments:
                    comments_summary = await summarize_comments_with_gpt(comments)
                    summary_text += "\n\n**[댓글 요약]**\n" + comments_summary
                else:
                    logger.debug("댓글을 가져오지 못했습니다.")
            else:
                logger.debug("영상 ID를 추출하지 못했습니다.")

        finally:
            if os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                    logger.debug("MP3 파일 삭제 완료: path=%s", mp3_path)
                except OSError:
                    logger.warning("MP3 파일 삭제 실패: path=%s", mp3_path, exc_info=True)

    return summary_text.strip()


async def process_youtube_link(url: str) -> str:
    try:
        link_kind = get_youtube_link_kind(url)
        if link_kind == YOUTUBE_POST_KIND:
            return await process_youtube_post_link(url)
        return await process_youtube_video_link(url)
    except YouTubeSummaryError:
        raise
    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        DownloadError,
        KeyError,
        OSError,
        OpenAIModelError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        YouTubeApiError,
    ) as exc:
        raise YouTubeSummaryError(
            "유튜브 요약을 처리하지 못했습니다. 잠시 후 다시 시도해주세요."
        ) from exc
