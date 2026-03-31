from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Final

import aiohttp
from dotenv import load_dotenv

from util.env_utils import getenv_clean, sanitize_environment

load_dotenv()
sanitize_environment()

ECOS_API_KEY = getenv_clean("ECOS_API_KEY")
ECOS_API_BASE_URL: Final = "https://ecos.bok.or.kr/api"
ECOS_STAT_CODE: Final = "731Y001"
ECOS_LANGUAGE: Final = "kr"
ECOS_FORMAT: Final = "json"
ECOS_MAX_ROWS: Final = 100
DEFAULT_LOOKBACK_DAYS: Final = 30
MAX_LOOKBACK_DAYS: Final = 365
SEOUL_TZ: Final = timezone(timedelta(hours=9))
REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(total=15)


@dataclass(frozen=True)
class CurrencySpec:
    code: str
    korean_name: str
    item_code: str | None
    scale: int = 1


@dataclass(frozen=True)
class RatePoint:
    point_date: date
    rate: float


@dataclass(frozen=True)
class ExchangeQuote:
    base: CurrencySpec
    target: CurrencySpec
    current_rate: float
    basis_date: date
    requested_days: int
    chart_points: list[RatePoint]


class ExchangeRateError(Exception):
    pass


class ExchangeRateConfigurationError(ExchangeRateError):
    pass


SUPPORTED_CURRENCIES: Final[dict[str, CurrencySpec]] = {
    "KRW": CurrencySpec(code="KRW", korean_name="원", item_code=None),
    "USD": CurrencySpec(code="USD", korean_name="달러", item_code="0000001"),
    "JPY": CurrencySpec(code="JPY", korean_name="엔", item_code="0000002", scale=100),
    "EUR": CurrencySpec(code="EUR", korean_name="유로", item_code="0000003"),
    "GBP": CurrencySpec(code="GBP", korean_name="파운드", item_code="0000012"),
    "CAD": CurrencySpec(code="CAD", korean_name="캐나다달러", item_code="0000013"),
    "CHF": CurrencySpec(code="CHF", korean_name="스위스프랑", item_code="0000014"),
    "HKD": CurrencySpec(code="HKD", korean_name="홍콩달러", item_code="0000015"),
    "AUD": CurrencySpec(code="AUD", korean_name="호주달러", item_code="0000017"),
    "SAR": CurrencySpec(code="SAR", korean_name="사우디리얄", item_code="0000020"),
    "AED": CurrencySpec(code="AED", korean_name="디르함", item_code="0000023"),
    "SGD": CurrencySpec(code="SGD", korean_name="싱가포르달러", item_code="0000024"),
    "MYR": CurrencySpec(code="MYR", korean_name="링깃", item_code="0000025"),
    "NZD": CurrencySpec(code="NZD", korean_name="뉴질랜드달러", item_code="0000026"),
    "CNY": CurrencySpec(code="CNY", korean_name="위안", item_code="0000053"),
    "THB": CurrencySpec(code="THB", korean_name="바트", item_code="0000028"),
    "IDR": CurrencySpec(code="IDR", korean_name="루피아", item_code="0000029", scale=100),
    "PHP": CurrencySpec(code="PHP", korean_name="페소", item_code="0000034"),
    "VND": CurrencySpec(code="VND", korean_name="동", item_code="0000035", scale=100),
    "INR": CurrencySpec(code="INR", korean_name="루피", item_code="0000037"),
}


def get_supported_currency(code: str) -> CurrencySpec:
    try:
        return SUPPORTED_CURRENCIES[code]
    except KeyError as exc:
        raise ExchangeRateError(f"지원하지 않는 통화 코드입니다: {code}") from exc


def _today_kst() -> date:
    return datetime.now(SEOUL_TZ).date()


def _build_paged_request_url(
    item_code: str,
    start_date: date,
    end_date: date,
    start_row: int,
    end_row: int,
) -> str:
    return (
        f"{ECOS_API_BASE_URL}/StatisticSearch/{ECOS_API_KEY}/{ECOS_FORMAT}/"
        f"{ECOS_LANGUAGE}/{start_row}/{end_row}/{ECOS_STAT_CODE}/D/"
        f"{start_date:%Y%m%d}/{end_date:%Y%m%d}/{item_code}"
    )


def _parse_ecos_date(raw_value: str) -> date:
    return datetime.strptime(raw_value, "%Y%m%d").date()


def _parse_ecos_rate(raw_value: str, scale: int) -> float:
    return float(raw_value) / scale


def _map_ecos_error(code: str, message: str) -> str:
    if code.startswith("INFO-200"):
        return "요청한 기간에 환율 데이터가 없습니다."
    if code.startswith("ERROR-"):
        lowered = message.lower()
        if "인증키" in message or "auth" in lowered:
            return "ECOS API 인증키를 확인해주세요."
        if "호출" in message or "limit" in lowered:
            return "ECOS API 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
        return f"ECOS API 오류가 발생했습니다: {message.strip()}"
    return message.strip() or "ECOS API 응답을 처리하지 못했습니다."


async def _fetch_series(
    session: aiohttp.ClientSession,
    currency: CurrencySpec,
    start_date: date,
    end_date: date,
) -> list[RatePoint]:
    if currency.code == "KRW":
        raise ExchangeRateError("KRW는 직접 조회 대상이 아닙니다.")

    async def _request_payload(start_row: int, end_row: int) -> dict:
        url = _build_paged_request_url(
            currency.item_code or "",
            start_date,
            end_date,
            start_row,
            end_row,
        )
        try:
            async with session.get(url) as response:
                return await response.json(content_type=None)
        except asyncio.TimeoutError as exc:
            raise ExchangeRateError("ECOS API 응답 시간이 초과되었습니다.") from exc
        except aiohttp.ClientError as exc:
            raise ExchangeRateError("ECOS API에 연결하지 못했습니다.") from exc
        except Exception as exc:
            raise ExchangeRateError("ECOS API 응답을 해석하지 못했습니다.") from exc

    payload = await _request_payload(1, ECOS_MAX_ROWS)

    result = payload.get("RESULT")
    if result:
        raise ExchangeRateError(
            _map_ecos_error(result.get("CODE", ""), result.get("MESSAGE", ""))
        )

    statistic_search = payload.get("StatisticSearch", {})
    total_count = int(statistic_search.get("list_total_count", 0) or 0)
    rows = list(statistic_search.get("row", []))
    while len(rows) < total_count:
        start_row = len(rows) + 1
        end_row = min(start_row + ECOS_MAX_ROWS - 1, total_count)
        payload = await _request_payload(start_row, end_row)
        result = payload.get("RESULT")
        if result:
            raise ExchangeRateError(
                _map_ecos_error(result.get("CODE", ""), result.get("MESSAGE", ""))
            )
        rows.extend(payload.get("StatisticSearch", {}).get("row", []))

    points: list[RatePoint] = []
    for row in rows:
        raw_date = row.get("TIME")
        raw_value = row.get("DATA_VALUE")
        if not raw_date or raw_value in (None, ""):
            continue
        try:
            points.append(
                RatePoint(
                    point_date=_parse_ecos_date(str(raw_date)),
                    rate=_parse_ecos_rate(str(raw_value), currency.scale),
                )
            )
        except ValueError:
            continue

    if not points:
        raise ExchangeRateError("조회 가능한 환율 데이터가 없습니다.")

    return sorted(points, key=lambda point: point.point_date)


def _build_pair_series(
    base: CurrencySpec,
    target: CurrencySpec,
    base_points: list[RatePoint] | None,
    target_points: list[RatePoint] | None,
) -> list[RatePoint]:
    if base.code == "KRW":
        assert target_points is not None
        return [
            RatePoint(point_date=point.point_date, rate=1 / point.rate)
            for point in target_points
            if point.rate
        ]

    if target.code == "KRW":
        assert base_points is not None
        return base_points

    assert base_points is not None
    assert target_points is not None

    target_by_date = {point.point_date: point.rate for point in target_points}
    pair_points: list[RatePoint] = []
    for point in base_points:
        target_rate = target_by_date.get(point.point_date)
        if not target_rate:
            continue
        pair_points.append(
            RatePoint(point_date=point.point_date, rate=point.rate / target_rate)
        )
    return sorted(pair_points, key=lambda point: point.point_date)


async def get_exchange_quote(
    base_code: str,
    target_code: str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> ExchangeQuote:
    if not ECOS_API_KEY:
        raise ExchangeRateConfigurationError(
            "ECOS_API_KEY 환경 변수가 설정되지 않았습니다."
        )

    base = get_supported_currency(base_code)
    target = get_supported_currency(target_code)

    if base.code == target.code:
        raise ExchangeRateError("기준통화와 대상통화는 서로 달라야 합니다.")
    if lookback_days < 1 or lookback_days > MAX_LOOKBACK_DAYS:
        raise ExchangeRateError(
            f"기간은 1일 이상 {MAX_LOOKBACK_DAYS}일 이하로 입력해주세요."
        )

    end_date = _today_kst()
    start_date = end_date - timedelta(days=lookback_days)

    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT, trust_env=False) as session:
        tasks = []
        if base.code != "KRW":
            tasks.append(_fetch_series(session, base, start_date, end_date))
        if target.code != "KRW":
            tasks.append(_fetch_series(session, target, start_date, end_date))

        results = await asyncio.gather(*tasks)

    result_index = 0
    base_series: list[RatePoint] | None = None
    target_series: list[RatePoint] | None = None

    if base.code != "KRW":
        base_series = results[result_index]
        result_index += 1
    if target.code != "KRW":
        target_series = results[result_index]

    pair_series = _build_pair_series(base, target, base_series, target_series)
    if not pair_series:
        raise ExchangeRateError("요청한 통화 조합으로 계산 가능한 환율 데이터가 없습니다.")

    latest = pair_series[-1]

    return ExchangeQuote(
        base=base,
        target=target,
        current_rate=latest.rate,
        basis_date=latest.point_date,
        requested_days=lookback_days,
        chart_points=pair_series,
    )
