from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import aiohttp

from util.earthquake.alerts import (
    EarthquakeAlertResult,
    process_jma_eew_event,
)
from util.earthquake.jma_eew import (
    JmaEewEvent,
    WOLFX_JMA_EEW_WEBSOCKET_URL,
    parse_jma_eew_message,
)


logger = logging.getLogger(__name__)
ProcessEvent = Callable[
    [object, JmaEewEvent],
    Awaitable[list[EarthquakeAlertResult]],
]
LogMessage = Callable[[str], None]


async def run_jma_eew_stream(
    bot: object,
    *,
    process_event: ProcessEvent = process_jma_eew_event,
    websocket_url: str = WOLFX_JMA_EEW_WEBSOCKET_URL,
    log: LogMessage = print,
) -> None:
    reconnect_delay = 2
    while not bot.is_closed():
        try:
            timeout = aiohttp.ClientTimeout(total=None, connect=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(
                    websocket_url,
                    heartbeat=30,
                    receive_timeout=90,
                    headers={"User-Agent": "DiscordBot JMA EEW alerts"},
                ) as websocket:
                    reconnect_delay = 2
                    log("일본 JMA EEW WebSocket 연결 완료")
                    await websocket.send_str("query_jmaeew")
                    await consume_jma_eew_messages(
                        bot,
                        websocket,
                        process_event=process_event,
                        log=log,
                    )
        except asyncio.CancelledError:
            raise
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            json.JSONDecodeError,
            ValueError,
        ):
            logger.warning("일본 JMA EEW WebSocket 연결 오류", exc_info=True)

        if bot.is_closed():
            return
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 30)


async def consume_jma_eew_messages(
    bot: object,
    websocket: object,
    *,
    process_event: ProcessEvent = process_jma_eew_event,
    log: LogMessage = print,
) -> int:
    processed_count = 0
    async for message in websocket:
        if message.type == aiohttp.WSMsgType.TEXT:
            try:
                payload = json.loads(message.data)
            except json.JSONDecodeError:
                logger.warning("일본 JMA EEW JSON 해석 실패")
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("type") == "heartbeat":
                await websocket.send_str("ping")
                continue
            if payload.get("type") == "pong":
                continue

            try:
                event = parse_jma_eew_message(payload)
            except ValueError:
                logger.warning("일본 JMA EEW 메시지 형식 오류", exc_info=True)
                continue
            if event is None:
                continue
            results = await process_event(bot, event)
            processed_count += 1
            _log_results(results, log)
            continue

        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        }:
            break
    return processed_count


def _log_results(
    results: list[EarthquakeAlertResult],
    log: LogMessage,
) -> None:
    for result in results:
        if result.status == "skipped":
            continue
        if result.status == "ok":
            log(
                f"일본 EEW 알림 처리 완료: guild={result.guild_id} "
                f"channel={result.channel_id} event={result.event_id} "
                f"serial={result.serial} action={result.action}"
            )
            continue
        log(
            f"일본 EEW 알림 실패: guild={result.guild_id} "
            f"channel={result.channel_id} event={result.event_id} "
            f"serial={result.serial} action={result.action} error={result.error}"
        )
