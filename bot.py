import asyncio
import os
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv

from func.find1557 import find1557
from func.spring_ai import spring_ai
from func.youtube_summary import check_youtube_link
from util.get_recent_messages import get_recent_messages
from util.db import create_tables, upsert_guild, upsert_user

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Client 설정, 변수
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
DISCORD_CLIENT = commands.Bot(command_prefix="/", intents=intents)
DISCORD_CLIENT.remove_command("help")
DISCORD_CLIENT.USER_MESSAGES = {}  # 길드별 -> 유저별 -> 메시지 리스트
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
SONPANNO_GUILD_ID = int(os.getenv("SONPANNO_GUILD_ID"))
SSAFY_GUILD_ID = int(os.getenv("SSAFY_GUILD_ID"))

# 기타 변수
SEOUL_TZ = timezone(timedelta(hours=9))  # 서울 시간대 설정 (UTC+9)


# Cog 로드
async def load_cogs():
    """Cog를 로드하고 초기 설정값을 전달합니다."""
    print("-------------------Cog 로드 시작-------------------")
    cogs_path = os.path.join(BASE_DIR, "cogs")
    entries = os.listdir(cogs_path)
    package_names = {
        entry
        for entry in entries
        if os.path.isdir(os.path.join(cogs_path, entry))
        and os.path.exists(os.path.join(cogs_path, entry, "__init__.py"))
    }

    for entry in sorted(entries):
        if entry.endswith(".py"):
            base_name = entry[:-3]
            if base_name in package_names:
                continue
            extension = f"cogs.{base_name}"
        elif entry in package_names:
            extension = f"cogs.{entry}"
        else:
            continue

        if extension in DISCORD_CLIENT.extensions:
            continue

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


async def load_variable():
    await asyncio.sleep(1)
    print()
    await load_recent_messages()
    await load_party_list()
    print("[최근 메시지, 파티] 로드 완료\n")


async def update_db_info():
    """Update guild and user info in DB on startup."""
    print("---------------- DB 정보 업데이트 시작 ----------------")
    try:
        await create_tables()

        for guild in DISCORD_CLIENT.guilds:
            await upsert_guild(guild.id, guild.name)

            # 멤버 정보 로드 (대규모 서버 대응)
            if not guild.chunked:
                await guild.chunk()

            # 멤버 정보 업데이트
            print(f"[{guild.name}] 멤버 {len(guild.members)}명 정보 업데이트...")
            for member in guild.members:
                # 유저의 닉네임(display_name) 사용
                name = member.display_name
                await upsert_user(member.id, name)

        print("---------------- DB 정보 업데이트 완료 ----------------\n")
    except Exception as e:
        print(f"[DB 업데이트 오류] {e}")


#! client.event
@DISCORD_CLIENT.event
async def on_ready():
    """
    봇 실행 준비.
    """
    # 파티 목록 등 기타 초기화
    await load_variable()
    await update_db_info()

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
async def on_member_join(member):
    """
    새로운 멤버 입장 시 DB 업데이트
    """
    try:
        await upsert_user(member.id, member.display_name)
    except Exception as e:
        print(f"[on_member_join 오류] {e}")


@DISCORD_CLIENT.event
async def on_member_update(before, after):
    """
    멤버 정보 변경 시(닉네임 등) DB 업데이트
    """
    try:
        if before.display_name != after.display_name:
            await upsert_user(after.id, after.display_name)
    except Exception as e:
        print(f"[on_member_update 오류] {e}")


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
        author_key = message.author.nick or message.author.name
    else:
        # DM 또는 봇(Self) 메시지 등은 name
        author_key = message.author.name

    #! 일반 채팅 저장
    if image_url:
        print(f"{timestamp} {author_key}: {message.content} [이미지 첨부]")
    else:
        print(f"{timestamp} {author_key}: {message.content}")

    # 길드별 -> 유저별 저장소 준비 (DM은 스킵)
    if not message.guild:
        # 길드 외(DM)는 길드별 로그에 포함하지 않음
        await DISCORD_CLIENT.process_commands(message)
        return
    guild_id = message.guild.id
    if guild_id not in DISCORD_CLIENT.USER_MESSAGES:
        DISCORD_CLIENT.USER_MESSAGES[guild_id] = {}
    guild_map = DISCORD_CLIENT.USER_MESSAGES[guild_id]
    if author_key not in guild_map:
        guild_map[author_key] = []

    #! 봇 메시지는 이하 명령 무시 / 단순 채팅 저장만
    if message.author == DISCORD_CLIENT.user:
        guild_map[author_key].append(
            {
                "author": author_key,
                "role": "assistant",
                "content": [
                    {"type": "input_text", "text": message.content},
                    {
                        "type": "input_image",
                        "image_url": image_url,
                    },
                ],
                "time": timestamp,
            }
        )
        return  # client 스스로가 보낸 메세지는 무시
    else:
        if image_url:
            guild_map[author_key].append(
                {
                    "author": author_key,
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": message.content},
                        {
                            "type": "input_image",
                            "image_url": image_url,
                        },
                    ],
                    "time": timestamp,
                }
            )
        else:
            guild_map[author_key].append(
                {
                    "author": author_key,
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": message.content},
                    ],
                    "time": timestamp,
                }
            )

    #! 유튜브 링크 처리
    await check_youtube_link(message)

    # !명령어 처리 루틴 호출
    await DISCORD_CLIENT.process_commands(message)

    # !1557 처리
    # SONPANNO_GUILD_ID 채널의 메시지에서만 1557 처리 수행
    try:
        if (
            getattr(message, "channel", None)
            and message.channel.id == SONPANNO_GUILD_ID
        ):
            await find1557(message)
    except Exception as e:
        # 1557 처리 중 예외는 전체 흐름을 막지 않도록 로깅만 수행
        print(f"[1557 처리 오류] {e}")

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


async def load_recent_messages(guild_id: int | None = None):
    print("------------------- 메시지 로드 -------------------")
    today = datetime.now(SEOUL_TZ).date()

    # 길드별 순회 (특정 길드만 요청 시 해당 길드만)
    guilds = (
        [g for g in DISCORD_CLIENT.guilds if g.id == guild_id]
        if guild_id is not None
        else list(DISCORD_CLIENT.guilds)
    )
    for guild in guilds:
        # 길드 맵 준비
        if guild.id not in DISCORD_CLIENT.USER_MESSAGES:
            DISCORD_CLIENT.USER_MESSAGES[guild.id] = {}

        # 해당 길드의 텍스트 채널 전체 순회 (필요시 특정 채널만 보려면 필터링)
        for channel in guild.text_channels:
            try:
                async for message in channel.history(limit=100):
                    # 날짜 필터(오늘)
                    message_kst = message.created_at.astimezone(SEOUL_TZ)
                    message_timestamp = message_kst.strftime("%Y-%m-%d %H:%M:%S")
                    if message_kst.date() != today:
                        continue

                    # 작성자 키(닉 우선)
                    if isinstance(message.author, discord.Member):
                        author_key = message.author.nick or message.author.name
                    else:
                        author_key = message.author.name

                    guild_map = DISCORD_CLIENT.USER_MESSAGES[guild.id]
                    if author_key not in guild_map:
                        guild_map[author_key] = []

                    # content 파츠 구성
                    parts = []
                    text = (message.content or "").strip()
                    if text:
                        parts.append({"type": "input_text", "text": text})

                    def _is_image(att):
                        try:
                            if getattr(att, "content_type", None):
                                return (
                                    str(att.content_type).lower().startswith("image/")
                                )
                        except Exception:
                            pass
                        name = (getattr(att, "filename", "") or "").lower()
                        return name.endswith(
                            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
                        )

                    for att in getattr(message, "attachments", []):
                        if _is_image(att):
                            url = getattr(att, "url", None) or getattr(
                                att, "proxy_url", None
                            )
                            if url:
                                parts.append({"type": "input_image", "image_url": url})

                    role = (
                        "assistant" if message.author == DISCORD_CLIENT.user else "user"
                    )
                    guild_map[author_key].append(
                        {
                            "author": author_key,
                            "role": role,
                            "content": (
                                parts if parts else [{"type": "input_text", "text": ""}]
                            ),
                            "time": message_timestamp,
                        }
                    )
            except Exception:
                # 채널 접근 권한 없음 등은 무시
                continue

        # 작성자별 오래된→최신 정렬
        for author in DISCORD_CLIENT.USER_MESSAGES[guild.id].keys():
            DISCORD_CLIENT.USER_MESSAGES[guild.id][author] = list(
                reversed(DISCORD_CLIENT.USER_MESSAGES[guild.id][author])
            )

        # 로그 샘플
        sample = get_recent_messages(client=DISCORD_CLIENT, guild_id=guild.id, limit=50)
        print(f"[guild={guild.id}] recent sample:\n", sample)

    print("---------------------------------------------------\n")


async def main():
    async with DISCORD_CLIENT:
        await load_cogs()
        await DISCORD_CLIENT.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
