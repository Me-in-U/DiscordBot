from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, Tuple

from .constants import BALANCE_FILE, SEOUL_TZ


class BalanceService:
    """JSON 기반 잔액/통계 저장소 헬퍼."""

    def __init__(self, file_path: str = BALANCE_FILE):
        self.file_path = file_path

    # 내부 유틸
    def _load_all(self) -> Dict[str, Dict[str, dict]]:
        if not os.path.isfile(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_all(self, data: Dict[str, Dict[str, dict]]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _ensure_user(
        self, data: Dict[str, Dict[str, dict]], guild_id: str, user_id: str
    ) -> None:
        if guild_id not in data:
            data[guild_id] = {}
        if user_id not in data[guild_id]:
            data[guild_id][user_id] = {
                "balance": 0,
                "last_daily": None,
                "wins": 0,
                "losses": 0,
                # Blackjack specific stats
                "bj_wins": 0,
                "bj_losses": 0,
                "bj_pushes": 0,
            }
        else:
            payload = data[guild_id][user_id]
            payload.setdefault("wins", 0)
            payload.setdefault("losses", 0)
            payload.setdefault("balance", 0)
            payload.setdefault("last_daily", None)
            payload.setdefault("bj_wins", 0)
            payload.setdefault("bj_losses", 0)
            payload.setdefault("bj_pushes", 0)

    # 공개 API
    def get_balance(self, guild_id: str, user_id: str) -> int:
        data = self._load_all()
        return int(data.get(guild_id, {}).get(user_id, {}).get("balance", 0))

    def set_balance(self, guild_id: str, user_id: str, amount: int) -> None:
        data = self._load_all()
        self._ensure_user(data, guild_id, user_id)
        data[guild_id][user_id]["balance"] = int(amount)
        self._save_all(data)

    def add_result(self, guild_id: str, user_id: str, is_win: bool) -> None:
        data = self._load_all()
        self._ensure_user(data, guild_id, user_id)
        key = "wins" if is_win else "losses"
        data[guild_id][user_id][key] = int(data[guild_id][user_id].get(key, 0)) + 1
        self._save_all(data)

    def get_stats(self, guild_id: str, user_id: str) -> Tuple[int, int, float]:
        data = self._load_all()
        user = data.get(guild_id, {}).get(user_id, {})
        wins = int(user.get("wins", 0) or 0)
        losses = int(user.get("losses", 0) or 0)
        total = wins + losses
        rate = (wins / total * 100) if total > 0 else 0.0
        return wins, losses, rate

    def get_last_daily(self, guild_id: str, user_id: str) -> str | None:
        data = self._load_all()
        return data.get(guild_id, {}).get(user_id, {}).get("last_daily")

    def set_last_daily(self, guild_id: str, user_id: str, date_str: str) -> None:
        data = self._load_all()
        self._ensure_user(data, guild_id, user_id)
        data[guild_id][user_id]["last_daily"] = date_str
        self._save_all(data)

    def can_use_daily(self, guild_id: str, user_id: str) -> bool:
        last = self.get_last_daily(guild_id, user_id)
        if last is None:
            return True
        today = datetime.now(SEOUL_TZ).date().isoformat()
        return last != today

    def get_guild_balances(self, guild_id: str) -> Dict[str, dict]:
        return self._load_all().get(guild_id, {})

    # ----- Blackjack specific API -----
    def add_blackjack_result(self, guild_id: str, user_id: str, outcome: str) -> None:
        """outcome: 'win' | 'lose' | 'push'"""
        data = self._load_all()
        self._ensure_user(data, guild_id, user_id)
        if outcome == "win":
            key = "bj_wins"
        elif outcome == "lose":
            key = "bj_losses"
        else:
            key = "bj_pushes"
        data[guild_id][user_id][key] = int(data[guild_id][user_id].get(key, 0)) + 1
        self._save_all(data)

    def get_blackjack_stats(
        self, guild_id: str, user_id: str
    ) -> Tuple[int, int, int, float]:
        data = self._load_all()
        user = data.get(guild_id, {}).get(user_id, {})
        wins = int(user.get("bj_wins", 0) or 0)
        losses = int(user.get("bj_losses", 0) or 0)
        pushes = int(user.get("bj_pushes", 0) or 0)
        total = wins + losses
        rate = (wins / total * 100) if total > 0 else 0.0
        return wins, losses, pushes, rate


balance_service = BalanceService()
