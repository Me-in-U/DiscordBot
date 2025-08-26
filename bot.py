import asyncio
import os
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv

from func.find1557 import find1557
from func.spring_ai import spring_ai
from func.youtube_summary import check_youtube_link

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Client 설정, 변수
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
DISCORD_CLIENT = commands.Bot(command_prefix="/", intents=intents)
DISCORD_CLIENT.remove_command("help")
DISCORD_CLIENT.USER_MESSAGES = {}  # 유저별 채팅팅 저장용 딕셔너리
DISCORD_CLIENT.SETTING_DATA = os.path.join(
    BASE_DIR, "settingData.json"
)  # settingData 파일 이름
DISCORD_CLIENT.PARTY_LIST = {}

# Spring AI
DISCORD_CLIENT.CONV_ID_AGGRESSIVE = None
DISCORD_CLIENT.CONV_ID_FRIENDLY = None
DISCORD_CLIENT.CONV_ID = None
DISCORD_CLIENT.SPRING_AI_MODE = False
DISCORD_CLIENT.SPRING_AI_STYLE = "공격적"

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("MY_CHANNEL_ID"))
TEST_CHANNEL_ID = int(os.getenv("TEST_CHANNEL_ID"))  # 테스트용 채널 ID
GUILD_ID = int(os.getenv("GUILD_ID"))  # 손팬노 길드 ID

# 기타 변수
SEOUL_TZ = timezone(timedelta(hours=9))  # 서울 시간대 설정 (UTC+9)


# Cog 로드
async def load_cogs():
    """Cog를 로드하고 초기 설정값을 전달합니다."""
    print("-------------------Cog 로드 시작-------------------")
    for filename in os.listdir("cogs"):
        if filename.endswith(".py"):
            extension = "cogs." + filename[:-3]
            await DISCORD_CLIENT.load_extension(extension)
    print("-------------------Cog 로드 완료-------------------\n")


async def load_party_list():
    """
    모든 길드의 카테고리 중 이름이 '-파티'로 끝나는 카테고리들을 DISCORD_CLIENT.PARTY_LIST에 저장합니다.
    """
    print("---------------- 파티 카테고리 로드 ----------------")
    for guild in DISCORD_CLIENT.guilds:
        for category in guild.categories:
            if category.name.endswith("-파티"):
                if guild.id not in DISCORD_CLIENT.PARTY_LIST:
                    DISCORD_CLIENT.PARTY_LIST[guild.id] = []
                DISCORD_CLIENT.PARTY_LIST[guild.id].append(category)
    # 저장된 결과를 서버 이름과 파티 목록으로 출력
    for guild in DISCORD_CLIENT.guilds:
        if guild.id in DISCORD_CLIENT.PARTY_LIST:
            party_names = [cat.name for cat in DISCORD_CLIENT.PARTY_LIST[guild.id]]
            print(f"{guild.name}: {party_names}")
    print("---------------------------------------------------\n")


def get_recent_messages(limit=20):
    all_msgs = []
    for msgs in DISCORD_CLIENT.USER_MESSAGES.values():
        all_msgs.extend(msgs)

    # 시간순 정렬 (최신순)
    all_msgs.sort(key=lambda m: m["time"], reverse=True)

    # 최근 N개만
    recent = all_msgs[:limit]

    # 문자열로 합치기
    lines = []
    for m in reversed(recent):  # 시간순으로 보려면 다시 뒤집기
        role = m.get("role", "user")
        content = m.get("content", "")
        lines.append(f"[{m['time']}] {role}: {content}")
    return "\n".join(lines)


async def load_variable():
    await asyncio.sleep(1)
    print()
    await load_recent_messages()
    await load_party_list()
    print("[최근 메시지, 파티] 로드 완료\n")


#! client.event
@DISCORD_CLIENT.event
async def on_ready():
    """
    봇 실행 준비.
    """
    # 파티 목록 등 기타 초기화
    await load_variable()

    # 슬래시 커맨드 등록(동기화)
    # 로드된 Cog 정보 출력
    print("Loaded Cogs:", DISCORD_CLIENT.cogs.keys())
    try:
        # 테스트 서버(개발용)에 우선 동기화
        # TEST_GUILD = discord.Object(id=GUILD_ID)
        # synced_test = await DISCORD_CLIENT.tree.sync(guild=TEST_GUILD)
        # print(f"[TEST SYNC] {len(synced_test)}개 명령어 동기화 (길드 ID={GUILD_ID})")

        # 글로벌 동기화
        synced_global = await DISCORD_CLIENT.tree.sync()
        print(f"[GLOBAL SYNC] {len(synced_global)}개 명령어 동기화")
    except Exception as e:
        print(f"슬래시 커맨드 동기화 실패: {e}")

    # 로그인 완료 로그
    print(f"Logged on as {DISCORD_CLIENT.user}!")
    r = datetime.now(SEOUL_TZ).weekday()
    weekday = ["월", "화", "수", "목", "금", "토", "일"]
    print(f"오늘은 {weekday[r]}요일입니다.")
    print(f"현재 시간: {datetime.now(SEOUL_TZ).strftime('%Y-%m-%d %H:%M:%S')}")


@DISCORD_CLIENT.event
async def on_message(message):
    """
    일반 메시지 처리
    """
    #! 현재 시간(서울 시간대 적용)으로 타임스탬프 생성
    timestamp = message.created_at.astimezone(SEOUL_TZ).strftime("%Y-%m-%d %H:%M:%S")

    image_url = None
    # 이미지 첨부 확인
    if message.attachments:
        image_url = message.attachments[0].url
    # 유저 닉네임 혹은 글로벌 이름 가져오기
    # 유저 이름 가져오기 (Member vs User 구분)
    if isinstance(message.author, discord.Member):
        # 서버 내 멤버라면 nick(별명) 우선, 없으면 username
        user = message.author.nick or message.author.name
    else:
        # DM 또는 봇(Self) 메시지 등은 name
        user = message.author.name

    #! 일반 채팅 저장
    if image_url:
        print(f"{timestamp} {user}: {message.content} [이미지 첨부]")
    else:
        print(f"{timestamp} {user}: {message.content}")

    if user not in DISCORD_CLIENT.USER_MESSAGES:
        DISCORD_CLIENT.USER_MESSAGES[user] = []

    #! 봇 메시지는 이하 명령 무시
    if message.author == DISCORD_CLIENT.user:
        DISCORD_CLIENT.USER_MESSAGES[user].append(
            {
                "role": "assistant",
                "content": message.content,
                "time": timestamp,
            }
        )
        return  # client 스스로가 보낸 메세지는 무시
    else:
        if image_url:
            DISCORD_CLIENT.USER_MESSAGES[user].append(
                {"content": message.content, "image_url": image_url, "time": timestamp}
            )
        else:
            DISCORD_CLIENT.USER_MESSAGES[user].append(
                {"content": message.content, "time": timestamp}
            )

    #! 유튜브 링크 처리
    await check_youtube_link(message)

    # !명령어 처리 루틴 호출
    await DISCORD_CLIENT.process_commands(message)

    # !1557 처리
    await find1557(message)

    # !스프링 AI
    await spring_ai(DISCORD_CLIENT, message)


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


@DISCORD_CLIENT.command(
    aliases=["핑"],
    help="봇 레이턴시 측정",
)
async def ping(ctx):
    await ctx.respond(f"퐁! Latency is {DISCORD_CLIENT.latency}")


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
    DISCORD_CLIENT.USER_MESSAGES["神᲼"] = []
    async for message in target_channel.history(limit=100):  # 최대 1557개 로드
        # print(message)
        message_timestamp = message.created_at.astimezone(SEOUL_TZ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        message_date = message.created_at.astimezone(
            SEOUL_TZ
        ).date()  # 메시지 날짜 확인
        if message_date != today:
            # print("skip", message_date, message.author, message.content)
            continue  # 오늘 날짜가 아니면 건너뛰기

        # print("added", message_date, message.author, message.content)

        # !각 메시지 작성자의 기록이 없으면 초기화
        if message.author.name not in DISCORD_CLIENT.USER_MESSAGES:
            DISCORD_CLIENT.USER_MESSAGES[message.author.name] = []

        if message.author == DISCORD_CLIENT.user:
            DISCORD_CLIENT.USER_MESSAGES[message.author.name].append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "time": message_timestamp,
                }
            )
        else:
            DISCORD_CLIENT.USER_MESSAGES[message.author.name].append(
                {"content": message.content, "time": message_timestamp}
            )
    print("---------------------------------------------------\n")

    for user in DISCORD_CLIENT.USER_MESSAGES:
        DISCORD_CLIENT.USER_MESSAGES[user] = list(
            reversed(DISCORD_CLIENT.USER_MESSAGES[user])
        )
    # print(DISCORD_CLIENT.USER_MESSAGES)


async def main():
    async with DISCORD_CLIENT:
        await load_cogs()
        await DISCORD_CLIENT.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
