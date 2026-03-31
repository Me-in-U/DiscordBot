from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final

import aiohttp
from dotenv import load_dotenv

from util.env_utils import getenv_clean, sanitize_environment

load_dotenv()
sanitize_environment()

ECOS_API_KEY = getenv_clean("ECOS_API_KEY")
ECOS_API_BASE_URL: Final = "https://ecos.bok.or.kr/api"
ECOS_LANGUAGE: Final = "kr"
ECOS_FORMAT: Final = "json"
ECOS_PAGE_SIZE: Final = 100
REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(total=15)
FOREIGN_RESERVES_STAT_CODE: Final = "902Y014"
FOREIGN_RESERVES_ITEM_CODE: Final = "KR"
FOREIGN_RESERVES_NAME: Final = "외환보유액"
DEFAULT_LOOKBACK_MONTHS: Final = 12
MAX_LOOKBACK_MONTHS: Final = 60


@dataclass(frozen=True)
class ForeignReservesPoint:
    point_date: date
    cycle: str
    raw_value_million_usd: Decimal
    amount_okr_usd: Decimal


@dataclass(frozen=True)
class ForeignReservesStat:
    class_name: str
    key_name: str
    basis_cycle: str
    unit_name: str
    raw_value_million_usd: Decimal
    amount_okr_usd: Decimal
    requested_months: int
    chart_points: list[ForeignReservesPoint]


class ForeignReservesError(Exception):
    pass


class ForeignReservesConfigurationError(ForeignReservesError):
    pass


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _subtract_months(value: date, months: int) -> date:
    total_months = value.year * 12 + (value.month - 1) - months
    year = total_months // 12
    month = total_months % 12 + 1
    return date(year, month, 1)


def _build_key_statistics_url(start_row: int, end_row: int) -> str:
    return (
        f"{ECOS_API_BASE_URL}/KeyStatisticList/{ECOS_API_KEY}/{ECOS_FORMAT}/"
        f"{ECOS_LANGUAGE}/{start_row}/{end_row}/"
    )


def _build_statistic_search_url(
    start_row: int,
    end_row: int,
    start_cycle: str,
    end_cycle: str,
) -> str:
    return (
        f"{ECOS_API_BASE_URL}/StatisticSearch/{ECOS_API_KEY}/{ECOS_FORMAT}/"
        f"{ECOS_LANGUAGE}/{start_row}/{end_row}/{FOREIGN_RESERVES_STAT_CODE}/M/"
        f"{start_cycle}/{end_cycle}/{FOREIGN_RESERVES_ITEM_CODE}"
    )


def _format_cycle(cycle: str) -> str:
    if len(cycle) == 6 and cycle.isdigit():
        return f"{cycle[:4]}-{cycle[4:]}"
    if len(cycle) == 8 and cycle.isdigit():
        return f"{cycle[:4]}-{cycle[4:6]}-{cycle[6:]}"
    if len(cycle) == 6 and cycle.endswith(("Q1", "Q2", "Q3", "Q4")):
        return f"{cycle[:4]} {cycle[4:]}"
    return cycle


def format_foreign_reserves_cycle(cycle: str) -> str:
    return _format_cycle(cycle)


def _parse_cycle_to_date(cycle: str) -> date:
    if len(cycle) == 6 and cycle.isdigit():
        return date(int(cycle[:4]), int(cycle[4:]), 1)
    raise ForeignReservesError(f"알 수 없는 기준월 형식입니다: {cycle}")


def _map_ecos_error(code: str, message: str) -> str:
    lowered = (message or "").lower()
    if code.startswith("INFO-200"):
        return "외환보유액 데이터를 찾지 못했습니다."
    if code.startswith("ERROR-"):
        if "인증키" in message or "auth" in lowered:
            return "ECOS API 인증키를 확인해주세요."
        if "호출" in message or "limit" in lowered:
            return "ECOS API 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
        return f"ECOS API 오류가 발생했습니다: {message.strip()}"
    return message.strip() or "ECOS API 응답을 처리하지 못했습니다."


async def _fetch_json(session: aiohttp.ClientSession, url: str) -> dict:
    try:
        async with session.get(url) as response:
            return await response.json(content_type=None)
    except asyncio.TimeoutError as exc:
        raise ForeignReservesError("ECOS API 응답 시간이 초과되었습니다.") from exc
    except aiohttp.ClientError as exc:
        raise ForeignReservesError("ECOS API에 연결하지 못했습니다.") from exc
    except Exception as exc:
        raise ForeignReservesError("ECOS API 응답을 해석하지 못했습니다.") from exc


async def _fetch_key_statistics(session: aiohttp.ClientSession) -> list[dict]:
    payload = await _fetch_json(session, _build_key_statistics_url(1, ECOS_PAGE_SIZE))
    result = payload.get("RESULT")
    if result:
        raise ForeignReservesError(
            _map_ecos_error(result.get("CODE", ""), result.get("MESSAGE", ""))
        )

    key_statistics = payload.get("KeyStatisticList", {})
    total_count = int(key_statistics.get("list_total_count", 0) or 0)
    rows = list(key_statistics.get("row", []))

    while len(rows) < total_count:
        start_row = len(rows) + 1
        end_row = min(start_row + ECOS_PAGE_SIZE - 1, total_count)
        payload = await _fetch_json(session, _build_key_statistics_url(start_row, end_row))
        result = payload.get("RESULT")
        if result:
            raise ForeignReservesError(
                _map_ecos_error(result.get("CODE", ""), result.get("MESSAGE", ""))
            )
        rows.extend(payload.get("KeyStatisticList", {}).get("row", []))

    return rows


async def _fetch_foreign_reserves_series(
    session: aiohttp.ClientSession,
    start_cycle: str,
    end_cycle: str,
) -> list[ForeignReservesPoint]:
    payload = await _fetch_json(
        session,
        _build_statistic_search_url(1, ECOS_PAGE_SIZE, start_cycle, end_cycle),
    )
    result = payload.get("RESULT")
    if result:
        raise ForeignReservesError(
            _map_ecos_error(result.get("CODE", ""), result.get("MESSAGE", ""))
        )

    statistic_search = payload.get("StatisticSearch", {})
    total_count = int(statistic_search.get("list_total_count", 0) or 0)
    rows = list(statistic_search.get("row", []))

    while len(rows) < total_count:
        start_row = len(rows) + 1
        end_row = min(start_row + ECOS_PAGE_SIZE - 1, total_count)
        payload = await _fetch_json(
            session,
            _build_statistic_search_url(start_row, end_row, start_cycle, end_cycle),
        )
        result = payload.get("RESULT")
        if result:
            raise ForeignReservesError(
                _map_ecos_error(result.get("CODE", ""), result.get("MESSAGE", ""))
            )
        rows.extend(payload.get("StatisticSearch", {}).get("row", []))

    points: list[ForeignReservesPoint] = []
    for row in rows:
        cycle = str(row.get("TIME", "")).strip()
        raw_value_text = str(row.get("DATA_VALUE", "")).strip()
        if not cycle or not raw_value_text:
            continue
        try:
            raw_value = Decimal(raw_value_text)
        except InvalidOperation:
            continue
        points.append(
            ForeignReservesPoint(
                point_date=_parse_cycle_to_date(cycle),
                cycle=cycle,
                raw_value_million_usd=raw_value,
                amount_okr_usd=raw_value / Decimal("100"),
            )
        )

    if not points:
        raise ForeignReservesError("조회 가능한 외환보유액 시계열이 없습니다.")

    return sorted(points, key=lambda point: point.point_date)


async def get_foreign_reserves(
    *,
    lookback_months: int = DEFAULT_LOOKBACK_MONTHS,
) -> ForeignReservesStat:
    if not ECOS_API_KEY:
        raise ForeignReservesConfigurationError(
            "ECOS_API_KEY 환경 변수가 설정되지 않았습니다."
        )
    if lookback_months < 1 or lookback_months > MAX_LOOKBACK_MONTHS:
        raise ForeignReservesError(
            f"기간은 1개월 이상 {MAX_LOOKBACK_MONTHS}개월 이하로 입력해주세요."
        )

    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT, trust_env=False) as session:
        key_statistics_rows = await _fetch_key_statistics(session)

        target_row = next(
            (row for row in key_statistics_rows if row.get("KEYSTAT_NAME") == FOREIGN_RESERVES_NAME),
            None,
        )
        if target_row is None:
            raise ForeignReservesError("ECOS에서 외환보유액 지표를 찾지 못했습니다.")

        latest_cycle = str(target_row.get("CYCLE", "")).strip()
        latest_month = _parse_cycle_to_date(latest_cycle)
        start_month = _subtract_months(_month_start(latest_month), lookback_months - 1)

        chart_points = await _fetch_foreign_reserves_series(
            session,
            start_month.strftime("%Y%m"),
            latest_month.strftime("%Y%m"),
        )

    latest_point = chart_points[-1]

    return ForeignReservesStat(
        class_name=str(target_row.get("CLASS_NAME", "")).strip(),
        key_name=str(target_row.get("KEYSTAT_NAME", "")).strip(),
        basis_cycle=latest_point.cycle,
        unit_name="백만달러",
        raw_value_million_usd=latest_point.raw_value_million_usd,
        amount_okr_usd=latest_point.amount_okr_usd,
        requested_months=lookback_months,
        chart_points=chart_points,
    )
