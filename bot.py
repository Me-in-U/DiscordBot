import asyncio
import os
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv

from requests_gpt import image_analysis, send_to_chatgpt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Client 설정, 변수
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
DISCORD_CLIENT = commands.Bot(command_prefix="!", intents=intents)
DISCORD_CLIENT.remove_command("help")
DISCORD_CLIENT.USER_MESSAGES = {}  # 유저별 채팅팅 저장용 딕셔너리
DISCORD_CLIENT.SETTING_DATA = os.path.join(
    BASE_DIR, "settingData.json"
)  # settingData 파일 이름

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("MY_CHANNEL_ID"))

# 기타 변수
NICKNAMES = {}  # 유저 닉네임 저장
SEOUL_TZ = timezone(timedelta(hours=9))  # 서울 시간대 설정 (UTC+9)


# Cog 로드
async def load_cogs():
    """Cog를 로드하고 초기 설정값을 전달합니다."""
    await DISCORD_CLIENT.load_extension("def_loop")
    await DISCORD_CLIENT.load_extension("def_rank")
    print("Cog 로드 완료\n")


async def load_variable():
    await asyncio.sleep(1)
    print()
    await load_recent_messages()
    await load_all_nicknames()
    print("최근 메시지, 닉네임 로드 완료\n")


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
    # 명령어 처리 루틴 호출
    await DISCORD_CLIENT.process_commands(message)


#! client.command
@DISCORD_CLIENT.command(
    aliases=["질문"],
    help="ChatGPT에게 질문합니다. '!질문 [질문 내용]' 형식으로 사용하세요.",
)
async def question(ctx):
    """
    커맨드 질문 처리
    ChatGPT
    """
    DISCORD_CLIENT.USER_MESSAGES[ctx.author].append(
        {"role": "user", "content": ctx.message.content}
    )

    # ChatGPT에 메시지 전달
    messages = [
        {
            "role": "system",
            "content": """아래는 유저가 말했던 기록이다.
            내용을 참고하도록 하고 맨 마지막이 질문이다.
            질문에 대한 답을 해라. 전체 대화 내용이 필요한 질문이면 밑에서 참고해라
            추가적인 질문요청, 궁금한점이 있는지 되묻지 말고 질문에만 답해라""",
        },
        {
            "role": "system",
            "content": f"전체 대화 내용 : {DISCORD_CLIENT.USER_MESSAGES}",
        },
        {
            "role": "user",
            "content": f"{ctx.author}의 질문 : {ctx.message.content}",
        },
        {
            "role": "system",
            "content": f"아래는 닉네임 정보:\n{NICKNAMES}\n",
        },
    ]

    # ChatGPT에 메시지 전달
    response = send_to_chatgpt(messages, temperature=0.4)

    # 봇 응답 기록
    DISCORD_CLIENT.USER_MESSAGES[ctx.author].append(
        {"role": "assistant", "content": response}
    )
    await ctx.reply(f"{response}")


@DISCORD_CLIENT.command(
    aliases=["신이시여", "신이여", "창섭님"],
    help="정상화의 신에게 질문합니다. '!신이시여 [질문 내용]' 형식으로 사용하세요.",
)
async def to_god(ctx):
    """
    커맨드 질문 처리
    ChatGPT
    """
    DISCORD_CLIENT.USER_MESSAGES[ctx.author].append(
        {"role": "user", "content": ctx.message.content}
    )

    # ChatGPT에 메시지 전달
    messages = [
        {
            "role": "system",
            "content": """당신은 세계 최고 정상화의 신, 게임 메이플스토리의 신창섭 디렉터이다.
            당신은 모든것을 정상화 하는 능력이 있다. 신으로써 아래 질문에 대한 답을 해야한다.
            당신은 모든것을 알고있다. 이에 답을하라. 정상화의 신이 말하는 말투로 말해라.
            문제가 있다면 해결하는 방향으로 정상화 시켜라.
            아래는 유저가 말했던 기록이다. 내용을 참고하도록 하고 맨 마지막이 질문이다.""",
        },
        {
            "role": "system",
            "content": f"전체 대화 내용 : {DISCORD_CLIENT.USER_MESSAGES}",
        },
        {
            "role": "user",
            "content": f"{ctx.author}의 질문 : {ctx.message.content}",
        },
        {
            "role": "system",
            "content": f"아래는 닉네임 정보:\n{NICKNAMES}\n",
        },
    ]

    # ChatGPT에 메시지 전달
    response = send_to_chatgpt(messages, temperature=0.7)

    # 봇 응답 기록
    DISCORD_CLIENT.USER_MESSAGES[ctx.author].append(
        {"role": "assistant", "content": response}
    )
    await ctx.reply(f"{response}")


@DISCORD_CLIENT.command(
    aliases=["요약"],
    help="채팅 내용을 요약합니다다. '!요약",
)
async def summary(ctx, *, text: str = None):
    """
    커맨드 요약 처리리
    오늘의 메시지 전체 요약
    """
    # 저장된 모든 대화 기록 확인
    if not DISCORD_CLIENT.USER_MESSAGES:
        await ctx.reply("**요약할 대화 내용이 없습니다.**")
        return

    request_message = text.strip() if text else ""

    # 요약 요청 메시지 생성
    messages = [
        {
            "role": "system",
            "content": """당신은 요약 전문가입니다. 주어진 대화 내용을 요약해주세요.
            전체적인 내용을 5줄 이내로 요약. 
            그 이후 각 유저가 한 말을 따로 요약한걸 추가해줘.
            닉네임 : 요약 형식으로
            자연스러운 말투로 말해줘.""",
        },
        {"role": "system", "content": f"추가 요청 사항 : {request_message}"},
        {
            "role": "system",
            "content": f"아래 채팅 내용을 요약해 주세요:\n{DISCORD_CLIENT.USER_MESSAGES}\n",
        },
        {
            "role": "system",
            "content": f"아래는 닉네임 정보:\n{NICKNAMES}\n",
        },
        {"role": "system", "content": "대화에 참여하지 않은 유저는 알려주지마"},
    ]

    # ChatGPT에 메시지 전달
    response = send_to_chatgpt(messages, temperature=0.6)

    # 응답 출력
    await ctx.reply(f"{response}")


@DISCORD_CLIENT.command(
    aliases=["번역", "버녁"],
    help="이전 채팅 내용을 한국어로 번역하거나 '!번역 [문장]' 형식으로 번역합니다.",
)
async def translate(ctx, *, text: str = None):
    """
    입력된 문장이 있으면 해당 문장을, 없으면 최근 메시지를 번역합니다.
    """
    if text:
        # 명령어 뒤에 입력된 문장이 있을 경우 해당 문장 번역
        target_message = text.strip()
    else:
        # 최근 메시지 탐색
        async for message in ctx.channel.history(limit=10):  # 최근 최대 10개 탐색
            if message.author != DISCORD_CLIENT.user and message.id != ctx.message.id:
                target_message = message.content
                break
        else:
            # 번역할 메시지가 없을 경우
            await ctx.reply("**번역할 메시지를 찾지 못했습니다.**")
            return

    # 번역 요청 메시지 생성
    messages = [
        {
            "role": "system",
            "content": """당신은 전문 번역가입니다. 
            대화 내용을 직역보다는 자연스럽게 한국어로 번역해 주세요. 
            번역된 문장 이외에 추가적인 설명은 필요 없습니다.""",
        },
        {
            "role": "system",
            "content": f"아래는 번역할 대화 내용입니다:\n{target_message}",
        },
    ]

    # ChatGPT에 메시지 전달
    translated_message = send_to_chatgpt(messages, temperature=0.5)

    # 번역 결과 출력
    await ctx.reply(translated_message)


@DISCORD_CLIENT.command(
    aliases=["해석"],
    help="이전 채팅 내용을 해석하거나 '!해석 [문장]' 형식으로 해석합니다.",
)
async def interpret(ctx, *, text: str = None):
    """
    입력된 문장이 있으면 해당 문장을, 없으면 최근 메시지를 해석합니다.
    """
    target_message = ""
    image_url = None

    if text:
        # 명령어 뒤에 입력된 문장이 있을 경우 해당 문장 번역
        target_message = text.strip()
        # 이미지 첨부 여부 확인
        if ctx.message.attachments:
            image_url = ctx.message.attachments[0].url
    else:
        # 최근 메시지 탐색
        async for message in ctx.channel.history(limit=10):  # 최근 최대 10개 탐색
            if message.author != DISCORD_CLIENT.user and message.id != ctx.message.id:
                target_message = message.content
                # 이미지 첨부 여부 확인
                if message.attachments:
                    image_url = message.attachments[0].url
                break
        else:
            # 번역할 메시지가 없을 경우
            await ctx.reply("**해석할 메시지를 찾지 못했습니다.**")
            return

    # 번역 요청 메시지 생성
    messages = [
        {
            "role": "system",
            "content": "당신은 문장 해석 전문가입니다. 대화 내용의 의미나 숨겨진 뜻을 찾아서 해석해주세요.",
        },
        {
            "role": "system",
            "content": f"아래는 해석할 대화 내용입니다:\n{target_message}",
        },
    ]

    if image_url:
        # 이미지와 텍스트를 처리
        interpreted = image_analysis(messages, image_url=image_url, temperature=0.6)
    else:
        # 텍스트만 처리
        interpreted = send_to_chatgpt(messages, temperature=0.6)

    # 번역 결과 출력
    await ctx.reply(interpreted)


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
    aliases=["help", "도움", "도뭉", "동움"],
    help="봇의 모든 명령어와 사용 방법을 출력합니다.",
)
async def custom_help(ctx):
    """
    봇의 명령어 목록과 설명을 출력합니다.
    """
    commands_info = [
        ("!질문 [질문 내용]", "ChatGPT에게 질문하고 답변을 받습니다."),
        ("!신이시여 [질문 내용]", "정상화의 신에게 질문하고 답변을 받습니다."),
        ("!요약 [추가 요청 사항 (선택)]", "최근 채팅 내용을 요약합니다."),
        (
            "!번역 [텍스트 (선택)]",
            "입력된 텍스트나 최근 채팅을 한국어로 번역합니다.",
        ),
        (
            "!해석 [텍스트 (선택)]",
            "입력된 텍스트나 최근 채팅의 의미를 해석합니다.",
        ),
        ("!채팅 [텍스트]", "봇이 입력된 텍스트를 대신 전송합니다."),
        ("!도움", "봇의 모든 명령어와 사용 방법을 출력합니다."),
        ("!솔랭 [닉네임#태그]", "롤 솔로랭크 데이터를 출력합니다."),
        ("!자랭 [닉네임#태그]", "롤 자유랭크 데이터를 출력합니다."),
        (
            "!일일랭크",
            "현재 자정 솔랭 출력 사용자를 출력합니다.",
        ),
        (
            "!일일랭크변경 [닉네임#태그]",
            "자정 솔랭 정보 출력을 새로운 사용자로 변경합니다.",
        ),
        (
            "!일일랭크루프 true/false",
            "자정 솔랭 출력 기능 on/off.",
        ),
    ]
    # 명령어 설명 생성
    help_message = "## ℹ️ 봇 명령어 목록:\n\n"
    for command, description in commands_info:
        help_message += f"- **{command}**\n\t {description}\n"

    # 명령어 출력
    await ctx.reply(help_message)


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
            NICKNAMES[member] = (
                member.display_name if member.display_name else member.name
            )
    print("---------------------------------------------------\n")


async def main():
    async with DISCORD_CLIENT:
        await load_cogs()
        await DISCORD_CLIENT.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
