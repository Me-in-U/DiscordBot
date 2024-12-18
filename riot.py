import os
import requests
from dotenv import load_dotenv

load_dotenv()
RIOT_KEY = os.getenv("RIOT_KEY")

if not RIOT_KEY:
    raise EnvironmentError("RIOT_KEY 환경 변수가 설정되지 않았습니다.")


REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Whale/4.29.282.14 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Charset": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://developer.riotgames.com",
    "X-Riot-Token": RIOT_KEY,
}


def get_rank_data(game_name, tag_line, rank_type="solo"):
    try:
        # Riot ID로 PUUID 조회
        player_data = requests.get(
            f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}",
            headers=REQUEST_HEADERS,
        ).json()
        print(player_data)

        # PUUID로 소환사 정보 조회
        puuid = player_data["puuid"]
        print(puuid)
        player = requests.get(
            f"https://kr.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}",
            headers=REQUEST_HEADERS,
        ).json()

        if "id" not in player:
            return f"{game_name}#{tag_line}의 소환사 정보를 찾을 수 없습니다."

        # 소환사 ID로 랭크 데이터 조회
        encrypted_summoner_id = player["id"]
        player_info = requests.get(
            f"https://kr.api.riotgames.com/lol/league/v4/entries/by-summoner/{encrypted_summoner_id}",
            headers=REQUEST_HEADERS,
        ).json()
        print(player_info)

        # 랭크 정보 추출
        first_is_solo = player_info[0]["queueType"] == "RANKED_SOLO_5x5"
        index = 0 if rank_type == "solo" else 1
        index = 1 - index if not first_is_solo else index

        rank_data = player_info[index]
        tier = rank_data["tier"]
        rank = rank_data["rank"]
        league_points = rank_data["leaguePoints"]
        wins = rank_data["wins"]
        losses = rank_data["losses"]

        rank_type_kor = "솔랭" if rank_type == "solo" else "자랭"
        win_rate = (wins / (wins + losses)) * 100
        # 반환 메시지
        return (
            f'## "{game_name}#{tag_line}" {rank_type_kor} 정보\n'
            f"티어: {tier} {rank} {league_points}포인트\n"
            f"승리: {wins} ({win_rate:.2f}%)\n"
            f"패배: {losses}"
        )
    except Exception as e:
        print(f"데이터를 가져오는 중 오류가 발생했습니다: {e}")
        return '데이터를 가져오는 중 오류가 발생했습니다\n "닉네임#테그"를 다시 확인해주세요요'


# game_name = "손성락"
# tag_line = "KR2"
# print(get_rank_data(game_name, tag_line))
