import asyncio
import os
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv

from def_simsim_e import simsim_chatbot
from def_youtube_summary import check_youtube_link
from requests_gpt import image_analysis, send_to_chatgpt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Client 설정, 변수
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
DISCORD_CLIENT = commands.Bot(command_prefix="!", intents=intents)
DISCORD_CLIENT.remove_command("help")
DISCORD_CLIENT.USER_MESSAGES = {}  # 유저별 채팅팅 저장용 딕셔너리
DISCORD_CLIENT.NICKNAMES = {}  # 유저 닉네임 저장
DISCORD_CLIENT.SETTING_DATA = os.path.join(
    BASE_DIR, "settingData.json"
)  # settingData 파일 이름
DISCORD_CLIENT.SIMSIM_MODE = False
DISCORD_CLIENT.SIMSIM_CHATS = []

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("MY_CHANNEL_ID"))

# 기타 변수
SEOUL_TZ = timezone(timedelta(hours=9))  # 서울 시간대 설정 (UTC+9)


# Cog 로드
async def load_cogs():
    """Cog를 로드하고 초기 설정값을 전달합니다."""
    print("-------------------Cog 로드 시작-------------------")
    await DISCORD_CLIENT.load_extension("def_custom_help")
    await DISCORD_CLIENT.load_extension("def_loop")
    await DISCORD_CLIENT.load_extension("def_party")
    await DISCORD_CLIENT.load_extension("def_questions")
    await DISCORD_CLIENT.load_extension("def_rank")
    print("-------------------Cog 로드 완료-------------------\n")


async def load_party_list():
    """
    모든 길드의 카테고리 중 이름이 '-파티'로 끝나는 카테고리들을 DISCORD_CLIENT.PARTY_LIST에 저장합니다.
    """
    print("---------------- 파티 카테고리 로드 ----------------")
    party_list = []
    for guild in DISCORD_CLIENT.guilds:
        for category in guild.categories:
            if category.name.endswith("-파티"):
                party_list.append(category)
    DISCORD_CLIENT.PARTY_LIST = party_list
    print(f"로딩된 파티 카테고리: {[c.name for c in party_list]}")
    print("---------------------------------------------------\n")


async def load_variable():
    await asyncio.sleep(1)
    print()
    await load_recent_messages()
    await load_all_nicknames()
    await load_party_list()
    print("[최근 메시지, 닉네임, 파티] 로드 완료\n")


#! client.event
@DISCORD_CLIENT.event
async def on_ready():
    """
    봇 실행 준비.
    """
    await load_variable()
    print(f"Logged on as {DISCORD_CLIENT.user}!")


@DISCORD_CLIENT.event
async def on_message(message):
    """
    일반 메시지 처리
    """
    print(f"일반 => {message.author}: {message.content}")
    if message.author not in DISCORD_CLIENT.USER_MESSAGES:
        DISCORD_CLIENT.USER_MESSAGES[message.author] = []
    if not message.content.startswith("!"):
        DISCORD_CLIENT.USER_MESSAGES[message.author].append(
            {"role": "user", "content": message.content}
        )
    if message.author == DISCORD_CLIENT.user:
        return  # client 스스로가 보낸 메세지는 무시

    #! 유튜브 링크 처리
    await check_youtube_link(message)

    # !심심이
    await simsim_chatbot(DISCORD_CLIENT, message)

    # !명령어 처리 루틴 호출
    await DISCORD_CLIENT.process_commands(message)


#! client.command
@DISCORD_CLIENT.command(
    aliases=["채팅"],
    help="입력된 채팅 내용을 봇이 대신 전송하고 원본 메시지를 삭제합니다.",
)
async def echo(ctx, *, text: str = None):
    """
    채팅 내용 그대로 보내기 (사용자 메시지는 삭제)
    """
    try:
        # 사용자의 메시지 삭제
        await ctx.message.delete()
    except discord.Forbidden:
        await ctx.send("# ⚠️ 메시지 삭제 권한이 없습니다.")
        return

    # 봇이 대신 메시지 전송
    message = text if text else ""
    await ctx.send(f"{message}")


async def load_recent_messages():
    target_channel = DISCORD_CLIENT.get_channel(CHANNEL_ID)
    print("------------------- 메시지 로드 -------------------")
    if not target_channel:
        print("대상 채널을 찾을 수 없습니다.")
        return

    # 오늘 날짜 기준으로 메시지 로드
    last_response = ""
    print(f"채널 '{target_channel.name}'에서 오늘의 메시지를 불러옵니다...")
    today = datetime.now(SEOUL_TZ).date()  # UTC 기준 오늘 날짜

    async for message in target_channel.history(limit=500):  # 최대 1000개 로드
        message_date = message.created_at.astimezone(
            SEOUL_TZ
        ).date()  # 메시지 날짜 확인
        if message_date != today:
            # print("skip", message_date, message.author, message.content)
            continue  # 오늘 날짜가 아니면 건너뛰기

        # print("added", message_date, message.author, message.content)
        if message.author not in DISCORD_CLIENT.USER_MESSAGES:
            DISCORD_CLIENT.USER_MESSAGES[message.author] = []

        # 봇 메시지 처리
        if message.author == DISCORD_CLIENT.user:
            last_response = message.content
        else:
            if message.content.startswith("!질문" or "!요약" or "!번역" or "!해석"):
                DISCORD_CLIENT.USER_MESSAGES[message.author].append(
                    {"role": "assistant", "content": last_response}
                )
            DISCORD_CLIENT.USER_MESSAGES[message.author].append(
                {"role": "user", "content": message.content}
            )
    print("---------------------------------------------------\n")

    for user in DISCORD_CLIENT.USER_MESSAGES:
        DISCORD_CLIENT.USER_MESSAGES[user] = list(
            reversed(DISCORD_CLIENT.USER_MESSAGES[user])
        )


async def load_all_nicknames():
    """
    채널에 있는 모든 멤버의 닉네임을 저장합니다.
    """
    # 봇이 참여한 모든 길드(서버) 확인
    print("------------------- 닉네임 로드 -------------------")
    for guild in DISCORD_CLIENT.guilds:
        print(f"서버 '{guild.name}'에서 멤버 목록을 불러옵니다...")
        for member in guild.members:
            DISCORD_CLIENT.NICKNAMES[member] = (
                member.display_name if member.display_name else member.name
            )
    print("---------------------------------------------------\n")


async def main():
    async with DISCORD_CLIENT:
        await load_cogs()
        await DISCORD_CLIENT.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
