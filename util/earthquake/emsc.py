from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

EMSC_WEBSOCKET_URL = (
    "wss://www.seismicportal.eu/standing_order/websocket"
)
EMSC_FDSN_EVENT_URL = (
    "https://www.seismicportal.eu/fdsnws/event/1/query"
)
EMSC_MIN_MAGNITUDE = 6.5
EMSC_KOREA_MIN_MAGNITUDE = 5.0
EMSC_KOREA_EVERYONE_MAGNITUDE = 5.5
EMSC_BACKFILL_MIN_MAGNITUDE = min(
    EMSC_MIN_MAGNITUDE,
    EMSC_KOREA_MIN_MAGNITUDE,
)
EMSC_EARTHQUAKE_EVENT_TYPE = "ke"
EMSC_CREATE_ACTIONS = frozenset({"create", "created", "insert", "inserted"})
EMSC_DELETE_ACTIONS = frozenset({"delete", "deleted", "remove", "removed"})
EMSC_JAPAN_REGION_MARKERS = (
    "JAPAN",
    "HONSHU",
    "HOKKAIDO",
    "KYUSHU",
    "SHIKOKU",
    "RYUKYU",
    "IZU ISLANDS",
    "BONIN ISLANDS",
    "VOLCANO ISLANDS",
    "SEA OF JAPAN",
)
EMSC_KOREA_REGION_MARKERS = ("KOREA",)
EMSC_KOREA_LATITUDE_RANGE = (33.0, 39.5)
EMSC_KOREA_LONGITUDE_RANGE = (124.0, 131.0)


@dataclass(frozen=True, slots=True)
class EmscEvent:
    event_id: str
    action: str
    occurred_at: datetime
    updated_at: datetime
    region: str
    latitude: float | None
    longitude: float | None
    magnitude: float | None
    magnitude_type: str
    depth_km: float | None
    authority: str
    source_catalog: str
    source_id: str
    event_type: str
    is_deleted: bool

    def is_at_least_magnitude(self, minimum: float) -> bool:
        return self.magnitude is not None and self.magnitude >= minimum

    @property
    def revision(self) -> str:
        return self.updated_at.astimezone(timezone.utc).isoformat()


def parse_emsc_message(payload: object) -> EmscEvent | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    properties = data.get("properties")
    if not isinstance(properties, dict):
        return None

    event_id = str(
        properties.get("unid") or data.get("id") or ""
    ).strip()
    occurred_at = _parse_datetime(properties.get("time"))
    updated_at = _parse_datetime(properties.get("lastupdate"))
    if not event_id or occurred_at is None:
        raise ValueError("EMSC 메시지의 필수 식별 정보가 없습니다.")
    if updated_at is None:
        updated_at = occurred_at

    action = str(payload.get("action") or "create").strip().lower()
    latitude, longitude = _coordinates(data, properties)
    return EmscEvent(
        event_id=event_id,
        action=action,
        occurred_at=occurred_at,
        updated_at=updated_at,
        region=str(properties.get("flynn_region") or "지역 정보 없음").strip(),
        latitude=latitude,
        longitude=longitude,
        magnitude=_optional_float(properties.get("mag")),
        magnitude_type=str(properties.get("magtype") or "").strip(),
        depth_km=_optional_float(properties.get("depth")),
        authority=str(properties.get("auth") or "EMSC").strip(),
        source_catalog=str(properties.get("source_catalog") or "").strip(),
        source_id=str(properties.get("source_id") or "").strip(),
        event_type=str(
            properties.get("evtype") or EMSC_EARTHQUAKE_EVENT_TYPE
        ).strip().lower(),
        is_deleted=action in EMSC_DELETE_ACTIONS,
    )


def is_japan_emsc_event(event: EmscEvent) -> bool:
    normalized_region = event.region.upper()
    return any(
        marker in normalized_region
        for marker in EMSC_JAPAN_REGION_MARKERS
    )


def is_korea_emsc_event(event: EmscEvent) -> bool:
    normalized_region = event.region.upper()
    if any(
        marker in normalized_region
        for marker in EMSC_KOREA_REGION_MARKERS
    ):
        return True
    if event.latitude is None or event.longitude is None:
        return False
    return (
        EMSC_KOREA_LATITUDE_RANGE[0]
        <= event.latitude
        <= EMSC_KOREA_LATITUDE_RANGE[1]
        and EMSC_KOREA_LONGITUDE_RANGE[0]
        <= event.longitude
        <= EMSC_KOREA_LONGITUDE_RANGE[1]
    )


def minimum_magnitude_for_emsc_event(event: EmscEvent) -> float:
    if is_korea_emsc_event(event):
        return EMSC_KOREA_MIN_MAGNITUDE
    return EMSC_MIN_MAGNITUDE


def is_earthquake_emsc_event(event: EmscEvent) -> bool:
    return event.event_type == EMSC_EARTHQUAKE_EVENT_TYPE


def _coordinates(
    data: dict,
    properties: dict,
) -> tuple[float | None, float | None]:
    latitude = _optional_float(properties.get("lat"))
    longitude = _optional_float(properties.get("lon"))
    geometry = data.get("geometry")
    if not isinstance(geometry, dict):
        return latitude, longitude
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return latitude, longitude
    if longitude is None:
        longitude = _optional_float(coordinates[0])
    if latitude is None:
        latitude = _optional_float(coordinates[1])
    return latitude, longitude


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
