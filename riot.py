import os
import requests
from dotenv import load_dotenv

load_dotenv()
RIOT_KEY = os.getenv("RIOT_KEY")

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Whale/4.29.282.14 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Charset": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://developer.riotgames.com",
    "X-Riot-Token": RIOT_KEY,
}


def get_rank_data(game_name, tag_line, rank_type="solo"):
    player_data = requests.get(
        f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}",
        headers=REQUEST_HEADERS,
    ).json()

    puuid = player_data["puuid"]
    player = requests.get(
        f"https://kr.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}",
        headers=REQUEST_HEADERS,
    ).json()

    encrypted_summoner_id = player["id"]
    player_info = requests.get(
        f"https://kr.api.riotgames.com/lol/league/v4/entries/by-summoner/{encrypted_summoner_id}",
        headers=REQUEST_HEADERS,
    ).json()
    print(player_info)

    first_is_solo = player_info[0]["queueType"] == "RANKED_SOLO_5x5"
    if first_is_solo:
        tier = player_info[0 if rank_type == "solo" else 1]["tier"]
        rank = player_info[0 if rank_type == "solo" else 1]["rank"]
        league_points = player_info[0 if rank_type == "solo" else 1]["leaguePoints"]
        wins = player_info[0 if rank_type == "solo" else 1]["wins"]
        losses = player_info[0 if rank_type == "solo" else 1]["losses"]
    else:
        tier = player_info[1 if rank_type == "solo" else 0]["tier"]
        rank = player_info[1 if rank_type == "solo" else 0]["rank"]
        league_points = player_info[1 if rank_type == "solo" else 0]["leaguePoints"]
        wins = player_info[1 if rank_type == "solo" else 0]["wins"]
        losses = player_info[1 if rank_type == "solo" else 0]["losses"]

    rank_type = "솔랭" if rank_type == "solo" else "자랭"
    # print("솔랭", tier, rank, league_points, "포인트", wins, losses)
    return f"## {game_name}#{tag_line} {rank_type} 정보\n티어: {tier} {rank} {league_points}포인트\n승리: {wins} ({(wins / (wins + losses)) * 100:.2f}%)\n패배: {losses}"


game_name = "손성락"
tag_line = "KR2"
print(get_rank_data(game_name, tag_line))
