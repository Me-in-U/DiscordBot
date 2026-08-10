from __future__ import annotations

import json
from dataclasses import dataclass, replace

from util.db import execute_query, fetch_one


EARTHQUAKE_ALERT_STATE_KEY_PREFIX = "earthquakeAlert"
EMSC_ALERT_STATE_KEY_PREFIX = "earthquakeAlertEmsc"
MAX_JMA_EEW_RECORDS = 64
MAX_EMSC_RECORDS = 128


@dataclass(frozen=True, slots=True)
class JmaEewMessageRecord:
    event_id: str
    serial: int
    message_id: int
    everyone_notified: bool = False


@dataclass(frozen=True, slots=True)
class EarthquakeAlertState:
    channel_id: int | None = None
    records: tuple[JmaEewMessageRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class EmscMessageRecord:
    event_id: str
    revision: str
    message_id: int
    everyone_notified: bool = False


@dataclass(frozen=True, slots=True)
class EmscAlertState:
    channel_id: int | None = None
    records: tuple[EmscMessageRecord, ...] = ()


async def load_earthquake_alert_state(
    guild_id: int,
) -> EarthquakeAlertState:
    row = await fetch_one(
        "SELECT setting_value FROM setting_data WHERE setting_key = %s",
        (_state_key(guild_id),),
    )
    if not row:
        return EarthquakeAlertState()

    payload = _decode_state_payload(row.get("setting_value"))
    records: list[JmaEewMessageRecord] = []
    raw_records = payload.get("records")
    if isinstance(raw_records, list):
        for item in raw_records:
            record = _decode_record(item)
            if record is not None:
                records.append(record)

    return EarthquakeAlertState(
        channel_id=_optional_int(payload.get("channelId")),
        records=tuple(records[-MAX_JMA_EEW_RECORDS:]),
    )


async def save_earthquake_alert_state(
    guild_id: int,
    state: EarthquakeAlertState,
) -> None:
    payload = {
        "channelId": state.channel_id,
        "records": [
            {
                "eventId": record.event_id,
                "serial": record.serial,
                "messageId": record.message_id,
                "everyoneNotified": record.everyone_notified,
            }
            for record in state.records[-MAX_JMA_EEW_RECORDS:]
        ],
    }
    await execute_query(
        "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
        (
            _state_key(guild_id),
            json.dumps(payload, ensure_ascii=False),
        ),
    )


async def load_emsc_alert_state(guild_id: int) -> EmscAlertState:
    row = await fetch_one(
        "SELECT setting_value FROM setting_data WHERE setting_key = %s",
        (_emsc_state_key(guild_id),),
    )
    if not row:
        return EmscAlertState()

    payload = _decode_state_payload(row.get("setting_value"))
    records: list[EmscMessageRecord] = []
    raw_records = payload.get("records")
    if isinstance(raw_records, list):
        for item in raw_records:
            record = _decode_emsc_record(item)
            if record is not None:
                records.append(record)

    return EmscAlertState(
        channel_id=_optional_int(payload.get("channelId")),
        records=tuple(records[-MAX_EMSC_RECORDS:]),
    )


async def save_emsc_alert_state(
    guild_id: int,
    state: EmscAlertState,
) -> None:
    payload = {
        "channelId": state.channel_id,
        "records": [
            {
                "eventId": record.event_id,
                "revision": record.revision,
                "messageId": record.message_id,
                "everyoneNotified": record.everyone_notified,
            }
            for record in state.records[-MAX_EMSC_RECORDS:]
        ],
    }
    await execute_query(
        "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
        (
            _emsc_state_key(guild_id),
            json.dumps(payload, ensure_ascii=False),
        ),
    )


async def delete_earthquake_alert_state(guild_id: int) -> None:
    await execute_query(
        "DELETE FROM setting_data WHERE setting_key IN (%s, %s)",
        (_state_key(guild_id), _emsc_state_key(guild_id)),
    )


def reset_earthquake_alert_state(channel_id: int) -> EarthquakeAlertState:
    return EarthquakeAlertState(channel_id=int(channel_id))


def reset_emsc_alert_state(channel_id: int) -> EmscAlertState:
    return EmscAlertState(channel_id=int(channel_id))


def find_jma_eew_record(
    state: EarthquakeAlertState,
    event_id: str,
) -> JmaEewMessageRecord | None:
    normalized_event_id = event_id.strip()
    return next(
        (
            record
            for record in reversed(state.records)
            if record.event_id == normalized_event_id
        ),
        None,
    )


def remember_jma_eew_message(
    state: EarthquakeAlertState,
    *,
    event_id: str,
    serial: int,
    message_id: int,
    everyone_notified: bool | None = None,
) -> EarthquakeAlertState:
    existing_record = find_jma_eew_record(state, event_id)
    resolved_everyone_notified = (
        existing_record.everyone_notified
        if everyone_notified is None and existing_record is not None
        else bool(everyone_notified)
    )
    record = JmaEewMessageRecord(
        event_id=event_id.strip(),
        serial=int(serial),
        message_id=int(message_id),
        everyone_notified=resolved_everyone_notified,
    )
    records = [
        existing
        for existing in state.records
        if existing.event_id != record.event_id
    ]
    records.append(record)
    return replace(
        state,
        records=tuple(records[-MAX_JMA_EEW_RECORDS:]),
    )


def find_emsc_record(
    state: EmscAlertState,
    event_id: str,
) -> EmscMessageRecord | None:
    normalized_event_id = event_id.strip()
    return next(
        (
            record
            for record in reversed(state.records)
            if record.event_id == normalized_event_id
        ),
        None,
    )


def remember_emsc_message(
    state: EmscAlertState,
    *,
    event_id: str,
    revision: str,
    message_id: int,
    everyone_notified: bool | None = None,
) -> EmscAlertState:
    existing_record = find_emsc_record(state, event_id)
    resolved_everyone_notified = (
        existing_record.everyone_notified
        if everyone_notified is None and existing_record is not None
        else bool(everyone_notified)
    )
    record = EmscMessageRecord(
        event_id=event_id.strip(),
        revision=revision.strip(),
        message_id=int(message_id),
        everyone_notified=resolved_everyone_notified,
    )
    records = [
        existing
        for existing in state.records
        if existing.event_id != record.event_id
    ]
    records.append(record)
    return replace(
        state,
        records=tuple(records[-MAX_EMSC_RECORDS:]),
    )


def _state_key(guild_id: int) -> str:
    return f"{EARTHQUAKE_ALERT_STATE_KEY_PREFIX}:{int(guild_id)}"


def _emsc_state_key(guild_id: int) -> str:
    return f"{EMSC_ALERT_STATE_KEY_PREFIX}:{int(guild_id)}"


def _decode_state_payload(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _decode_record(value: object) -> JmaEewMessageRecord | None:
    if not isinstance(value, dict):
        return None
    event_id = str(value.get("eventId") or "").strip()
    serial = _optional_int(value.get("serial"))
    message_id = _optional_int(value.get("messageId"))
    if not event_id or serial is None or message_id is None:
        return None
    return JmaEewMessageRecord(
        event_id=event_id,
        serial=serial,
        message_id=message_id,
        everyone_notified=bool(value.get("everyoneNotified", False)),
    )


def _decode_emsc_record(value: object) -> EmscMessageRecord | None:
    if not isinstance(value, dict):
        return None
    event_id = str(value.get("eventId") or "").strip()
    revision = str(value.get("revision") or "").strip()
    message_id = _optional_int(value.get("messageId"))
    if not event_id or not revision or message_id is None:
        return None
    return EmscMessageRecord(
        event_id=event_id,
        revision=revision,
        message_id=message_id,
        everyone_notified=bool(value.get("everyoneNotified", False)),
    )


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
