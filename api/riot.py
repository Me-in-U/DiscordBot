from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict

import aiohttp
from dotenv import load_dotenv

from util.env_utils import getenv_clean, sanitize_environment


load_dotenv()
sanitize_environment()
RIOT_KEY = getenv_clean("RIOT_KEY")

if not RIOT_KEY:
    raise EnvironmentError("RIOT_KEY 환경 변수가 설정되지 않았습니다.")


RankType = Literal["solo", "flex"]
QUEUE_BY_RANK_TYPE: dict[RankType, str] = {
    "solo": "RANKED_SOLO_5x5",
    "flex": "RANKED_FLEX_SR",
}
RANK_TYPE_KOR: dict[RankType, str] = {
    "solo": "솔랭",
    "flex": "자랭",
}
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Whale/4.29.282.14 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Charset": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://developer.riotgames.com",
    "X-Riot-Token": RIOT_KEY,
}


class RiotRankData(TypedDict):
    game_name: str
    tag_line: str
    tier: str
    rank: str
    league_points: int
    wins: int
    losses: int
    rank_type_kor: str
    win_rate: float


class RiotRankLookupError(Exception):
    """Raised when Riot rank data cannot be fetched or mapped."""


class _RiotSession(Protocol):
    def get(self, url: str, *, headers: dict[str, str]) -> Any:
        ...


async def _fetch_json(
    session: _RiotSession,
    url: str,
    *,
    endpoint_label: str,
) -> Any:
    try:
        async with session.get(url, headers=REQUEST_HEADERS) as response:
            payload = await response.json()
            if response.status < 200 or response.status >= 300:
                message = _riot_error_message(payload)
                raise RiotRankLookupError(
                    f"{endpoint_label} 조회 실패: HTTP {response.status} {message}".strip()
                )
            return payload
    except RiotRankLookupError:
        raise
    except aiohttp.ClientError as exc:
        raise RiotRankLookupError(f"{endpoint_label} 요청 실패: {exc}") from exc


def _riot_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        status = payload.get("status")
        if isinstance(status, dict) and status.get("message"):
            return str(status["message"])
        if payload.get("message"):
            return str(payload["message"])
    return ""


def _build_rank_data(
    *,
    game_name: str,
    tag_line: str,
    entries: Any,
    rank_type: RankType,
) -> RiotRankData:
    if not isinstance(entries, list):
        raise RiotRankLookupError("랭크 응답 형식이 올바르지 않습니다.")

    target_queue = QUEUE_BY_RANK_TYPE[rank_type]
    rank_data = next(
        (
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("queueType") == target_queue
        ),
        None,
    )
    if rank_data is None:
        raise RiotRankLookupError(f"{RANK_TYPE_KOR[rank_type]} 랭크 정보를 찾지 못했습니다.")

    wins = int(rank_data.get("wins", 0))
    losses = int(rank_data.get("losses", 0))
    total_games = wins + losses
    win_rate = (wins / total_games * 100) if total_games else 0.0
    return {
        "game_name": game_name,
        "tag_line": tag_line,
        "tier": str(rank_data["tier"]),
        "rank": str(rank_data["rank"]),
        "league_points": int(rank_data["leaguePoints"]),
        "wins": wins,
        "losses": losses,
        "rank_type_kor": RANK_TYPE_KOR[rank_type],
        "win_rate": win_rate,
    }


async def get_rank_data(
    game_name: str,
    tag_line: str,
    rank_type: RankType = "solo",
    *,
    session: _RiotSession | None = None,
) -> RiotRankData:
    if rank_type not in QUEUE_BY_RANK_TYPE:
        raise ValueError("rank_type은 'solo' 또는 'flex'여야 합니다.")

    async def _get_with_session(active_session: _RiotSession) -> RiotRankData:
        account_payload = await _fetch_json(
            active_session,
            f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}",
            endpoint_label="Riot ID",
        )
        if not isinstance(account_payload, dict) or not account_payload.get("puuid"):
            raise RiotRankLookupError("Riot ID 응답에서 PUUID를 찾지 못했습니다.")

        entries = await _fetch_json(
            active_session,
            f"https://kr.api.riotgames.com/lol/league/v4/entries/by-puuid/{account_payload['puuid']}",
            endpoint_label="랭크 정보",
        )
        return _build_rank_data(
            game_name=game_name,
            tag_line=tag_line,
            entries=entries,
            rank_type=rank_type,
        )

    if session is not None:
        return await _get_with_session(session)

    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT, trust_env=False) as client:
        return await _get_with_session(client)
