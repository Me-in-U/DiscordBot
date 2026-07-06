from __future__ import annotations

import hashlib
from typing import Any, Protocol, Sequence, TypeVar


MAPLESTORY_NOTICE_STATE_LIMIT = 50
MAPLESTORY_NOTICE_SENT_MESSAGE_LIMIT = 10
MAPLESTORY_NOTICE_COMPLETED_STATUS = "completed"
MAPLESTORY_NOTICE_PRE_COMPLETION_STATUSES = frozenset(
    {"scheduled", "in_progress", "extended"}
)


class MapleStoryNoticeLike(Protocol):
    notice_id: str
    category: str
    title: str
    summary: str
    body_text: str


NoticeT = TypeVar("NoticeT", bound=MapleStoryNoticeLike)


def get_maplestory_notice_maintenance_status(
    notice: MapleStoryNoticeLike,
) -> str | None:
    return classify_maplestory_notice_maintenance_status(
        notice.category,
        notice.title,
    )


def classify_maplestory_notice_maintenance_status(
    category: str,
    title: str,
) -> str | None:
    label = "".join(f"{category or ''} {title or ''}".split())
    if "점검완료" in label:
        return MAPLESTORY_NOTICE_COMPLETED_STATUS
    if "점검중" in label:
        return "in_progress"
    if "연장" in label and "점검" in label:
        return "extended"
    if "점검예정" in label or "점검" in label:
        return "scheduled"
    return None


def is_maplestory_notice_completion(notice: MapleStoryNoticeLike) -> bool:
    return (
        get_maplestory_notice_maintenance_status(notice)
        == MAPLESTORY_NOTICE_COMPLETED_STATUS
    )


def build_maplestory_notice_fingerprint(notice: MapleStoryNoticeLike) -> str:
    payload = "\n".join(
        [
            notice.notice_id,
            notice.category,
            notice.title,
            notice.summary,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_maplestory_notice_body_fingerprint(notice: MapleStoryNoticeLike) -> str:
    body_text = getattr(notice, "body_text", "") or notice.summary
    payload = "\n".join(
        [
            notice.notice_id,
            notice.category,
            notice.title,
            body_text,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def maplestory_notice_state_from_notices(
    notices: Sequence[MapleStoryNoticeLike],
    *,
    limit: int = MAPLESTORY_NOTICE_STATE_LIMIT,
) -> dict[str, Any]:
    state: dict[str, Any] = {"notices": {}, "recentNoticeIds": []}
    for notice in notices[:limit]:
        remember_maplestory_notice_in_state(state, notice, limit=limit)
    return state


def find_maplestory_notice_updates(
    notices: Sequence[NoticeT],
    state: dict[str, Any] | None,
) -> list[NoticeT]:
    updates, _checked_state, _migrated = find_maplestory_notice_updates_with_state(
        notices,
        state,
    )
    return updates


def find_maplestory_notice_updates_with_state(
    notices: Sequence[NoticeT],
    state: dict[str, Any] | None,
) -> tuple[list[NoticeT], dict[str, Any], bool]:
    normalized = normalize_maplestory_notice_state(state)
    stored_notices = normalized["notices"]
    updates: list[NoticeT] = []
    migrated = False
    for notice in notices:
        stored = stored_notices.get(notice.notice_id)
        fingerprint = build_maplestory_notice_fingerprint(notice)
        if not isinstance(stored, dict) or stored.get("fingerprint") != fingerprint:
            updates.append(notice)
            continue

        body_fingerprint = build_maplestory_notice_body_fingerprint(notice)
        if not stored.get("bodyFingerprint"):
            stored["bodyFingerprint"] = body_fingerprint
            migrated = True
            continue

        if stored.get("bodyFingerprint") != body_fingerprint:
            updates.append(notice)

    return updates, normalized, migrated


def normalize_maplestory_notice_state(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    notices: dict[str, Any] = {}
    recent_ids: list[str] = []
    if isinstance(state, dict):
        raw_notices = state.get("notices")
        if isinstance(raw_notices, dict):
            notices = {
                str(notice_id): value
                for notice_id, value in raw_notices.items()
                if isinstance(value, dict)
            }
        raw_recent_ids = state.get("recentNoticeIds")
        if isinstance(raw_recent_ids, list):
            recent_ids = [str(notice_id) for notice_id in raw_recent_ids if notice_id]
    return {"notices": notices, "recentNoticeIds": recent_ids}


def get_maplestory_notice_pre_completion_message_records(
    state: dict[str, Any],
    notice: MapleStoryNoticeLike,
    *,
    channel_id: int,
) -> list[dict[str, Any]]:
    if not is_maplestory_notice_completion(notice):
        return []

    normalized = normalize_maplestory_notice_state(state)
    stored = normalized["notices"].get(notice.notice_id)
    if not isinstance(stored, dict):
        return []

    records = _normalize_sent_message_records(stored.get("sentMessages"))
    return [
        record
        for record in records
        if record.get("channelId") == int(channel_id)
        and _sent_message_record_status(record)
        in MAPLESTORY_NOTICE_PRE_COMPLETION_STATUSES
    ]


def remember_maplestory_notice_in_state(
    state: dict[str, Any],
    notice: MapleStoryNoticeLike,
    *,
    limit: int = MAPLESTORY_NOTICE_STATE_LIMIT,
    channel_id: int | None = None,
    message_id: int | None = None,
) -> None:
    normalized = normalize_maplestory_notice_state(state)
    notice_id = str(notice.notice_id)
    previous = normalized["notices"].get(notice_id)
    sent_messages = (
        _normalize_sent_message_records(previous.get("sentMessages"))
        if isinstance(previous, dict)
        else []
    )
    notice_status = get_maplestory_notice_maintenance_status(notice)
    if notice_status == MAPLESTORY_NOTICE_COMPLETED_STATUS:
        sent_messages = [
            record
            for record in sent_messages
            if _sent_message_record_status(record)
            not in MAPLESTORY_NOTICE_PRE_COMPLETION_STATUSES
        ]

    if channel_id is not None and message_id is not None:
        normalized_channel_id = int(channel_id)
        normalized_message_id = int(message_id)
        sent_messages = [
            record
            for record in sent_messages
            if not (
                record.get("channelId") == normalized_channel_id
                and record.get("messageId") == normalized_message_id
            )
        ]
        sent_messages.append(
            {
                "channelId": normalized_channel_id,
                "messageId": normalized_message_id,
                "status": notice_status or "notice",
                "title": notice.title,
            }
        )
        sent_messages = sent_messages[-MAPLESTORY_NOTICE_SENT_MESSAGE_LIMIT:]

    notice_entry = {
        "fingerprint": build_maplestory_notice_fingerprint(notice),
        "bodyFingerprint": build_maplestory_notice_body_fingerprint(notice),
        "title": notice.title,
        "category": notice.category,
    }
    if sent_messages:
        notice_entry["sentMessages"] = sent_messages
    normalized["notices"][notice_id] = notice_entry
    recent_ids = [
        notice_id
        for notice_id in normalized["recentNoticeIds"]
        if notice_id != str(notice.notice_id)
    ]
    recent_ids.insert(0, str(notice.notice_id))
    normalized["recentNoticeIds"] = recent_ids[:limit]
    known_ids = set(normalized["recentNoticeIds"])
    normalized["notices"] = {
        notice_id: value
        for notice_id, value in normalized["notices"].items()
        if notice_id in known_ids
    }
    state.clear()
    state.update(normalized)


def _normalize_sent_message_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    records: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            channel_id = int(item.get("channelId"))
            message_id = int(item.get("messageId"))
        except (TypeError, ValueError):
            continue
        key = (channel_id, message_id)
        if key in seen:
            continue
        seen.add(key)

        record: dict[str, Any] = {
            "channelId": channel_id,
            "messageId": message_id,
        }
        status = str(item.get("status") or "")
        title = str(item.get("title") or "")
        if status:
            record["status"] = status
        if title:
            record["title"] = title
        records.append(record)
    return records


def _sent_message_record_status(record: dict[str, Any]) -> str | None:
    status = record.get("status")
    if isinstance(status, str) and status:
        return status
    title = record.get("title")
    if isinstance(title, str):
        return classify_maplestory_notice_maintenance_status("", title)
    return None
