from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


WOLFX_JMA_EEW_WEBSOCKET_URL = "wss://ws-api.wolfx.jp/jma_eew"
JMA_EEW_MIN_MAGNITUDE = 5.5
JMA_EEW_EVERYONE_MAGNITUDE = 7.0
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True, slots=True)
class JmaEewWarnArea:
    name: str
    minimum_intensity: str
    maximum_intensity: str
    report_type: str
    arrival_status: str


@dataclass(frozen=True, slots=True)
class JmaEewEvent:
    event_id: str
    serial: int
    announced_at: datetime
    origin_at: datetime | None
    title: str
    code_type: str
    issue_source: str
    issue_status: str
    hypocenter: str
    latitude: float | None
    longitude: float | None
    magnitude: float | None
    depth_km: float | None
    max_intensity: str
    warn_areas: tuple[JmaEewWarnArea, ...]
    is_sea: bool
    is_training: bool
    is_assumption: bool
    is_warning: bool
    is_final: bool
    is_cancelled: bool

    def is_at_least_magnitude(self, minimum: float) -> bool:
        return self.magnitude is not None and self.magnitude >= minimum


def parse_jma_eew_message(payload: object) -> JmaEewEvent | None:
    if not isinstance(payload, dict) or payload.get("type") != "jma_eew":
        return None

    event_id = str(payload.get("EventID") or "").strip()
    serial = _optional_int(payload.get("Serial"))
    announced_at = _parse_jst_datetime(payload.get("AnnouncedTime"))
    if not event_id or serial is None or announced_at is None:
        raise ValueError("JMA EEW 메시지의 필수 식별 정보가 없습니다.")

    issue = payload.get("Issue")
    if not isinstance(issue, dict):
        issue = {}

    warn_areas = payload.get("WarnArea")
    parsed_warn_areas: list[JmaEewWarnArea] = []
    if isinstance(warn_areas, list):
        for item in warn_areas:
            area = _parse_warn_area(item)
            if area is not None:
                parsed_warn_areas.append(area)

    return JmaEewEvent(
        event_id=event_id,
        serial=serial,
        announced_at=announced_at,
        origin_at=_parse_jst_datetime(payload.get("OriginTime")),
        title=str(payload.get("Title") or "").strip(),
        code_type=str(payload.get("CodeType") or "").strip(),
        issue_source=str(issue.get("Source") or "").strip(),
        issue_status=str(issue.get("Status") or "").strip(),
        hypocenter=str(payload.get("Hypocenter") or "진원 정보 없음").strip(),
        latitude=_optional_float(payload.get("Latitude")),
        longitude=_optional_float(payload.get("Longitude")),
        magnitude=_optional_float(
            payload.get("Magunitude", payload.get("Magnitude"))
        ),
        depth_km=_optional_float(payload.get("Depth")),
        max_intensity=str(payload.get("MaxIntensity") or "미상").strip(),
        warn_areas=tuple(parsed_warn_areas),
        is_sea=bool(payload.get("isSea")),
        is_training=bool(payload.get("isTraining")),
        is_assumption=bool(payload.get("isAssumption")),
        is_warning=bool(payload.get("isWarn")),
        is_final=bool(payload.get("isFinal")),
        is_cancelled=bool(payload.get("isCancel")),
    )


def is_recent_jma_eew(
    event: JmaEewEvent,
    *,
    now: datetime | None = None,
    maximum_age_seconds: int = 120,
) -> bool:
    current_time = now or datetime.now(timezone.utc)
    announced_at = event.announced_at.astimezone(timezone.utc)
    age_seconds = (current_time - announced_at).total_seconds()
    return -30 <= age_seconds <= maximum_age_seconds


def _parse_warn_area(value: object) -> JmaEewWarnArea | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("Chiiki") or "").strip()
    if not name:
        return None
    return JmaEewWarnArea(
        name=name,
        minimum_intensity=str(value.get("Shindo2") or "").strip(),
        maximum_intensity=str(value.get("Shindo1") or "").strip(),
        report_type=str(value.get("Type") or "").strip(),
        arrival_status=str(value.get("Arrive") or "").strip(),
    )


def _parse_jst_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(
            value.strip(),
            "%Y/%m/%d %H:%M:%S",
        ).replace(tzinfo=JST)
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
