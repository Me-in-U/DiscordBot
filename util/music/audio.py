from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

import discord


logger = logging.getLogger(__name__)


class BufferedOpusSource(discord.AudioSource):
    def __init__(self, source: discord.AudioSource) -> None:
        self.source = source
        self.packets: deque[bytes] = deque()
        self.ended = False

    def prime(self) -> None:
        # 첫 read 지연이 Discord 전송 시계에 포함되지 않도록 20ms 패킷 10개를 준비한다.
        for _ in range(10):
            packet = self.source.read()
            if not packet:
                self.ended = True
                break
            self.packets.append(packet)
        if not self.packets:
            raise ValueError("FFmpeg가 재생 가능한 오디오를 반환하지 않았습니다.")

    def read(self) -> bytes:
        if self.packets:
            return self.packets.popleft()
        return b"" if self.ended else self.source.read()

    def is_opus(self) -> bool:
        return self.source.is_opus()

    def cleanup(self) -> None:
        self.source.cleanup()


async def prepare_opus_source(source: discord.AudioSource) -> BufferedOpusSource:
    buffered = BufferedOpusSource(source)
    started = time.perf_counter()
    try:
        await asyncio.wait_for(asyncio.to_thread(buffered.prime), timeout=15.0)
    except (Exception, asyncio.CancelledError):
        # 프로세스를 종료해 대기 중인 read도 해제한다.
        try:
            await asyncio.to_thread(buffered.cleanup)
        except Exception:
            logger.exception("음악 시작 버퍼 실패 후 FFmpeg 정리 실패")
        raise
    logger.info(
        "음악 시작 버퍼 준비: packets=%d elapsed=%.3fs",
        len(buffered.packets), time.perf_counter() - started,
    )
    return buffered
