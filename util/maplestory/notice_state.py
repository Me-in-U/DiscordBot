from __future__ import annotations

import hashlib
from typing import Any, Protocol, Sequence, TypeVar


MAPLESTORY_NOTICE_STATE_LIMIT = 50


class MapleStoryNoticeLike(Protocol):
    notice_id: str
    category: str
    title: str
    summary: str
    body_text: str


NoticeT = TypeVar("NoticeT", bound=MapleStoryNoticeLike)


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


def remember_maplestory_notice_in_state(
    state: dict[str, Any],
    notice: MapleStoryNoticeLike,
    *,
    limit: int = MAPLESTORY_NOTICE_STATE_LIMIT,
) -> None:
    normalized = normalize_maplestory_notice_state(state)
    normalized["notices"][notice.notice_id] = {
        "fingerprint": build_maplestory_notice_fingerprint(notice),
        "bodyFingerprint": build_maplestory_notice_body_fingerprint(notice),
        "title": notice.title,
        "category": notice.category,
    }
    recent_ids = [
        notice_id
        for notice_id in normalized["recentNoticeIds"]
        if notice_id != notice.notice_id
    ]
    recent_ids.insert(0, notice.notice_id)
    normalized["recentNoticeIds"] = recent_ids[:limit]
    known_ids = set(normalized["recentNoticeIds"])
    normalized["notices"] = {
        notice_id: value
        for notice_id, value in normalized["notices"].items()
        if notice_id in known_ids
    }
    state.clear()
    state.update(normalized)
