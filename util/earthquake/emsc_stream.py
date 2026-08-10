from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import aiohttp

from util.earthquake.alerts import EarthquakeAlertResult
from util.earthquake.emsc import (
    EMSC_BACKFILL_MIN_MAGNITUDE,
    EMSC_FDSN_EVENT_URL,
    EMSC_WEBSOCKET_URL,
    EmscEvent,
    parse_emsc_message,
)
from util.earthquake.emsc_alerts import process_emsc_event


logger = logging.getLogger(__name__)
EMSC_RECONNECT_BACKFILL_WINDOW = timedelta(minutes=10)
ProcessEvent = Callable[
    [object, EmscEvent],
    Awaitable[list[EarthquakeAlertResult]],
]
LogMessage = Callable[[str], None]


async def run_emsc_stream(
    bot: object,
    *,
    process_event: ProcessEvent = process_emsc_event,
    websocket_url: str = EMSC_WEBSOCKET_URL,
    log: LogMessage = print,
) -> None:
    reconnect_delay = 2
    has_connected = False
    while not bot.is_closed():
        try:
            timeout = aiohttp.ClientTimeout(total=None, connect=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(
                    websocket_url,
                    heartbeat=30,
                    receive_timeout=180,
                    headers={"User-Agent": "DiscordBot EMSC earthquake alerts"},
                ) as websocket:
                    reconnect_delay = 2
                    log("EMSC 전 세계 지진 WebSocket 연결 완료")
                    if has_connected:
                        await _recover_emsc_updates(
                            bot,
                            session,
                            process_event=process_event,
                            log=log,
                        )
                    has_connected = True
                    await consume_emsc_messages(
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
            logger.warning("EMSC 지진 WebSocket 연결 오류", exc_info=True)

        if bot.is_closed():
            return
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 30)


async def _recover_emsc_updates(
    bot: object,
    session: aiohttp.ClientSession,
    *,
    process_event: ProcessEvent = process_emsc_event,
    log: LogMessage = print,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    updated_after = current_time - EMSC_RECONNECT_BACKFILL_WINDOW
    params = {
        "format": "json",
        "minmag": f"{EMSC_BACKFILL_MIN_MAGNITUDE:.1f}",
        "updatedafter": updated_after.isoformat().replace("+00:00", "Z"),
        "orderby": "time-asc",
        "limit": "100",
    }
    try:
        async with session.get(
            EMSC_FDSN_EVENT_URL,
            params=params,
        ) as response:
            response.raise_for_status()
            payload = await response.json()
    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        json.JSONDecodeError,
        ValueError,
    ):
        logger.warning("EMSC 재연결 누락분 조회 실패", exc_info=True)
        return 0

    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        return 0

    processed_count = 0
    for feature in features:
        try:
            event = parse_emsc_message(
                {"action": "update", "data": feature}
            )
        except ValueError:
            logger.warning("EMSC 누락분 메시지 형식 오류", exc_info=True)
            continue
        if event is None:
            continue
        results = await process_event(bot, event)
        processed_count += 1
        _log_results(results, log)
    if processed_count:
        log(f"EMSC 재연결 누락분 처리 완료: {processed_count}건")
    return processed_count


async def consume_emsc_messages(
    bot: object,
    websocket: object,
    *,
    process_event: ProcessEvent = process_emsc_event,
    log: LogMessage = print,
) -> int:
    processed_count = 0
    async for message in websocket:
        if message.type == aiohttp.WSMsgType.TEXT:
            try:
                payload = json.loads(message.data)
            except json.JSONDecodeError:
                logger.warning("EMSC 지진 JSON 해석 실패")
                continue
            try:
                event = parse_emsc_message(payload)
            except ValueError:
                logger.warning("EMSC 지진 메시지 형식 오류", exc_info=True)
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
                f"EMSC 지진 알림 처리 완료: guild={result.guild_id} "
                f"channel={result.channel_id} event={result.event_id} "
                f"action={result.action}"
            )
            continue
        log(
            f"EMSC 지진 알림 실패: guild={result.guild_id} "
            f"channel={result.channel_id} event={result.event_id} "
            f"action={result.action} error={result.error}"
        )
