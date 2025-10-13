from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
SETTINGS_PATH = BASE_DIR / "channel_settings.json"


def _load() -> Dict[str, Dict[str, int]]:
    def _try_load(path: Path) -> Dict:
        try:
            with path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}

    data: Dict = {}
    if SETTINGS_PATH.exists():
        data = _try_load(SETTINGS_PATH)
    else:
        # Fallback to backup if main is missing
        bak = SETTINGS_PATH.with_suffix(".bak")
        if bak.exists():
            data = _try_load(bak)
        else:
            return {}
    # If main was unreadable, try backup
    if not isinstance(data, dict) or not data:
        bak = SETTINGS_PATH.with_suffix(".bak")
        if bak.exists():
            data = _try_load(bak)

    if not isinstance(data, dict):
        return {}

    cleaned: Dict[str, Dict[str, int]] = {}
    for gid, channels in data.items():
        normalized = _normalize_channels(channels)
        if normalized:
            cleaned[str(gid)] = normalized
    return cleaned


def _normalize_channels(raw: object) -> Dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    result: Dict[str, int] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _save(data: Dict[str, Dict[str, int]]) -> None:
    """Atomically write settings to disk to avoid truncation/corruption."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = SETTINGS_PATH.with_suffix(".tmp")
    bak_path = SETTINGS_PATH.with_suffix(".bak")
    # Write to temp
    with tmp_path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.flush()
        os.fsync(fp.fileno())
    # Backup existing file
    if SETTINGS_PATH.exists():
        try:
            if bak_path.exists():
                bak_path.unlink(missing_ok=True)  # type: ignore[arg-type]
            SETTINGS_PATH.replace(bak_path)
        except Exception:
            pass
    # Atomic replace
    os.replace(tmp_path, SETTINGS_PATH)


def get_channel(guild_id: int, purpose: str) -> Optional[int]:
    data = _load()
    guild_data = data.get(str(guild_id))
    if not guild_data:
        return None
    value = guild_data.get(purpose)
    return int(value) if value is not None else None


def set_channel(guild_id: int, purpose: str, channel_id: Optional[int]) -> None:
    data = _load()
    key = str(guild_id)
    if channel_id is None:
        if key in data and purpose in data[key]:
            data[key].pop(purpose, None)
            if not data[key]:
                data.pop(key, None)
    else:
        data.setdefault(key, {})[purpose] = int(channel_id)
    _save(data)


def get_channels_by_purpose(purpose: str) -> Dict[int, int]:
    data = _load()
    result: Dict[int, int] = {}
    for guild_id, channels in data.items():
        if not isinstance(channels, dict):
            continue
        channel_id = channels.get(purpose)
        if channel_id is not None:
            try:
                result[int(guild_id)] = int(channel_id)
            except ValueError:
                continue
    return result


def get_settings_for_guild(guild_id: int) -> Dict[str, int]:
    data = _load()
    guild_data = data.get(str(guild_id), {})
    return {str(k): int(v) for k, v in guild_data.items() if v is not None}
