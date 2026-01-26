from __future__ import annotations

from typing import Dict, Tuple
from datetime import datetime
from util.db import execute_query, fetch_one, fetch_all
from .constants import SEOUL_TZ


class BalanceService:
    """MySQL based balance/stats storage helper."""

    def __init__(self):
        pass

    async def get_balance(self, guild_id: str, user_id: str) -> int:
        query = (
            "SELECT balance FROM gambling_balances WHERE guild_id = %s AND user_id = %s"
        )
        row = await fetch_one(query, (str(guild_id), str(user_id)))
        return row["balance"] if row else 0

    async def set_balance(self, guild_id: str, user_id: str, amount: int) -> None:
        query = """
            INSERT INTO gambling_balances (guild_id, user_id, balance) VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE balance = VALUES(balance)
        """
        await execute_query(query, (str(guild_id), str(user_id), amount))

    async def add_result(self, guild_id: str, user_id: str, is_win: bool) -> None:
        col = "wins" if is_win else "losses"
        query = f"""
            INSERT INTO gambling_balances (guild_id, user_id, {col}) VALUES (%s, %s, 1)
            ON DUPLICATE KEY UPDATE {col} = {col} + 1
        """
        await execute_query(query, (str(guild_id), str(user_id)))

    async def get_stats(self, guild_id: str, user_id: str) -> Tuple[int, int, float]:
        query = "SELECT wins, losses FROM gambling_balances WHERE guild_id = %s AND user_id = %s"
        row = await fetch_one(query, (str(guild_id), str(user_id)))
        wins = row["wins"] if row else 0
        losses = row["losses"] if row else 0
        total = wins + losses
        rate = (wins / total * 100) if total > 0 else 0.0
        return wins, losses, rate

    async def get_last_daily(self, guild_id: str, user_id: str) -> str | None:
        query = "SELECT last_daily FROM gambling_balances WHERE guild_id = %s AND user_id = %s"
        row = await fetch_one(query, (str(guild_id), str(user_id)))
        if row and row["last_daily"]:
            return str(row["last_daily"])
        return None

    async def set_last_daily(self, guild_id: str, user_id: str, date_str: str) -> None:
        query = """
            INSERT INTO gambling_balances (guild_id, user_id, last_daily) VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE last_daily = VALUES(last_daily)
        """
        await execute_query(query, (str(guild_id), str(user_id), date_str))

    async def can_use_daily(self, guild_id: str, user_id: str) -> bool:
        last = await self.get_last_daily(guild_id, user_id)
        if last is None:
            return True
        today = datetime.now(SEOUL_TZ).date().isoformat()
        return last != today

    async def get_guild_balances(self, guild_id: str) -> Dict[str, dict]:
        # Needed for ranking
        query = "SELECT * FROM gambling_balances WHERE guild_id = %s"
        rows = await fetch_all(query, (str(guild_id),))
        result = {}
        for row in rows:
            uid = row["user_id"]
            result[uid] = {
                "balance": row["balance"],
                "wins": row["wins"],
                "losses": row["losses"],
                "bj_wins": row["bj_wins"],
                "bj_losses": row["bj_losses"],
                "bj_pushes": row["bj_pushes"],
            }
        return result

    # ----- Blackjack specific API -----
    async def add_blackjack_result(
        self, guild_id: str, user_id: str, outcome: str
    ) -> None:
        """outcome: 'win' | 'lose' | 'push'"""
        if outcome == "win":
            col = "bj_wins"
        elif outcome == "lose":
            col = "bj_losses"
        else:
            col = "bj_pushes"

        query = f"""
            INSERT INTO gambling_balances (guild_id, user_id, {col}) VALUES (%s, %s, 1)
            ON DUPLICATE KEY UPDATE {col} = {col} + 1
        """
        await execute_query(query, (str(guild_id), str(user_id)))

    async def get_blackjack_stats(
        self, guild_id: str, user_id: str
    ) -> Tuple[int, int, int, float]:
        query = "SELECT bj_wins, bj_losses, bj_pushes FROM gambling_balances WHERE guild_id = %s AND user_id = %s"
        row = await fetch_one(query, (str(guild_id), str(user_id)))
        wins = row["bj_wins"] if row else 0
        losses = row["bj_losses"] if row else 0
        pushes = row["bj_pushes"] if row else 0
        total = wins + losses
        rate = (wins / total * 100) if total > 0 else 0.0
        return wins, losses, pushes, rate


balance_service = BalanceService()
