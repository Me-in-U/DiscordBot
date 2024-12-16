# This example requires the 'message_content' intent.
import os
from datetime import datetime, time, timedelta, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from openai import OpenAI

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")
CHANNEL_ID = os.getenv("MY_CHANNEL_ID")

# Client 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="!", intents=intents)
client.remove_command("help")

clientGPT = OpenAI(api_key=OPENAI_KEY)

# 유저별 채팅팅 저장용 딕셔너리
user_messages = {}

# 유저 닉네임 저장
nicknames = {}

# 서울 시간대 설정 (UTC+9)
seoul_tz = timezone(timedelta(hours=9))


#! client.event
@client.event
async def on_ready():
    """
    봇 실행 준비.
    """
    print(f"Logged on as {client.user}!")
    await load_all_nicknames()  # 채널의 모든 멤버 닉네임 저장
    await load_recent_messages()  # 최근 메시지 로드
    reset_user_messages.start()  # 자정 루프 시작
    # print_time.start()  # 1초마다 현재 시간 출력 시작


@client.event
async def on_message(message):
    """
    일반 메시지 처리
    """
    print(f"일반 => {message.author}: {message.content}")
    if message.author not in user_messages:
        user_messages[message.author] = []
    if not message.content.startswith("!"):
        user_messages[message.author].append(
            {"role": "user", "content": message.content}
        )
    if message.author == client.user:
        return  # client 스스로가 보낸 메세지는 무시
    # 명령어 처리 루틴 호출
    await client.process_commands(message)


#! client.command
@client.command(
    aliases=["질문"],
    help="ChatGPT에게 질문합니다. '!질문 [질문 내용]' 형식으로 사용하세요.",
)
async def question(ctx):
    """
    커맨드 질문 처리
    ChatGPT
    """
    user_messages[ctx.author].append({"role": "user", "content": ctx.message.content})
    # ChatGPT에 메시지 전달
    response = send_to_chatgpt(user_messages[ctx.author], temperature=0.4)
    # 봇 응답 기록
    user_messages[ctx.author].append({"role": "assistant", "content": response})
    await ctx.reply(f"{response}")


@client.command(
    aliases=["요약"],
    help="채팅 내용을 요약합니다다. '!요약",
)
async def summary(ctx, *, text: str = None):
    """
    커맨드 요약 처리리
    오늘의 메시지 전체 요약
    """
    # 저장된 모든 대화 기록 확인
    if not user_messages:
        await ctx.reply("**요약할 대화 내용이 없습니다.**")
        return

    request_message = text if text else ""

    # 요약 요청 메시지 생성
    messages = [
        {
            "role": "system",
            "content": "당신은 요약 전문가입니다. 주어진 대화 내용을 요약해주세요. ",
        },
        {
            "role": "system",
            "content": "전체적인 내용을 5줄 이내로 요약. 그 이후 각 유저가 한 말을 따로 요약한걸 추가해줘 닉네임 : 요약 형식으로 ",
        },
        {
            "role": "system",
            "content": "자연스러운 말투로 말하기",
        },
        {"role": "system", "content": f"추가 요청 사항 : {request_message}"},
        {
            "role": "system",
            "content": f"아래 채팅 내용을 요약해 주세요:\n{user_messages}\n",
        },
        {"role": "system", "content": f"아래는 닉네임 정보:\n{nicknames}\n"},
        {"role": "system", "content": "대화에 참여하지 않은 유저는 알려주지마"},
    ]

    # ChatGPT에 메시지 전달
    response = send_to_chatgpt(messages, temperature=0.6)

    # 응답 출력
    await ctx.reply(f"{response}")


@client.command(
    aliases=["번역"],
    help="이전 채팅 내용을 한국어로 번역하거나 '!번역 [문장]' 형식으로 번역합니다.",
)
async def translate(ctx, *, text: str = None):
    """
    입력된 문장이 있으면 해당 문장을, 없으면 최근 메시지를 번역합니다.
    """
    if text:
        # 명령어 뒤에 입력된 문장이 있을 경우 해당 문장 번역
        target_message = text
    else:
        # 최근 메시지 탐색
        async for message in ctx.channel.history(limit=10):  # 최근 최대 10개 탐색
            if message.author != client.user and message.id != ctx.message.id:
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
            "content": "당신은 전문 번역가입니다. 대화 내용을 직역보다는 자연스럽게 한국어로 번역해 주세요. 번역된 문장 이외에 추가적인 설명은 필요 없습니다.",
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


@client.command(
    aliases=["해석"],
    help="이전 채팅 내용을 해석하거나 '!해석 [문장]' 형식으로 해석합니다.",
)
async def interpret(ctx, *, text: str = None):
    """
    입력된 문장이 있으면 해당 문장을, 없으면 최근 메시지를 해석합니다.
    """
    if text:
        # 명령어 뒤에 입력된 문장이 있을 경우 해당 문장 번역
        target_message = text
    else:
        # 최근 메시지 탐색
        async for message in ctx.channel.history(limit=10):  # 최근 최대 10개 탐색
            if message.author != client.user and message.id != ctx.message.id:
                target_message = message.content
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

    # ChatGPT에 메시지 전달
    translated_message = send_to_chatgpt(messages, temperature=0.6)

    # 번역 결과 출력
    await ctx.reply(translated_message)


@client.command(
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


@client.command(
    aliases=["help", "도움"], help="봇의 모든 명령어와 사용 방법을 출력합니다."
)
async def custom_help(ctx):
    """
    봇의 명령어 목록과 설명을 출력합니다.
    """
    commands_info = [
        ("!질문 [질문 내용]", "ChatGPT에게 질문하고 답변을 받습니다."),
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
    ]
    # 명령어 설명 생성
    help_message = "## 봇 명령어 목록:\n\n"
    for command, description in commands_info:
        help_message += f"- **{command}**\n\t {description}\n"

    # 명령어 출력
    await ctx.reply(help_message)


#! client.loop
@tasks.loop(seconds=1)
async def print_time():
    """
    1초마다 현재 시간을 출력합니다.
    """
    current_time = datetime.now(seoul_tz).strftime("%Y-%m-%d %H:%M:%S")
    print(f"현재 시간 (UTC+9): {current_time}")


@tasks.loop(time=time(hour=0, minute=0, tzinfo=seoul_tz))  # 매일 자정
async def reset_user_messages():
    """
    매일 자정에 user_messages를 초기화합니다.
    """
    # 손팬
    target_channel = client.get_channel(CHANNEL_ID)

    global user_messages
    user_messages.clear()

    print(f"[{datetime.now()}] user_messages 초기화 완료.")
    await target_channel.send("📢 새로운 하루가 시작됩니다.")


#! def
async def load_all_nicknames():
    """
    채널에 있는 모든 멤버의 닉네임을 저장합니다.
    """
    # 봇이 참여한 모든 길드(서버) 확인
    for guild in client.guilds:
        print(f"서버 '{guild.name}'에서 멤버 목록을 불러옵니다...")
        for member in guild.members:
            nicknames[member] = (
                member.display_name if member.display_name else member.name
            )


async def load_recent_messages():
    target_channel = client.get_channel(CHANNEL_ID)

    if not target_channel:
        print("대상 채널을 찾을 수 없습니다.")
        return

    # 오늘 날짜 기준으로 메시지 로드
    last_response = ""
    print(f"채널 '{target_channel.name}'에서 오늘의 메시지를 불러옵니다...")
    today = datetime.now(seoul_tz).date()  # UTC 기준 오늘 날짜

    async for message in target_channel.history(limit=500):  # 최대 1000개 로드
        message_date = message.created_at.astimezone(
            seoul_tz
        ).date()  # 메시지 날짜 확인
        if message_date != today:
            # print("skip", message_date, message.author, message.content)
            continue  # 오늘 날짜가 아니면 건너뛰기

        # print("added", message_date, message.author, message.content)
        if message.author not in user_messages:
            user_messages[message.author] = []

        # 봇 메시지 처리
        if message.author == client.user:
            last_response = message.content
        else:
            if message.content.startswith("!질문" or "!요약" or "!번역" or "!해석"):
                user_messages[message.author].append(
                    {"role": "assistant", "content": last_response}
                )
            user_messages[message.author].append(
                {"role": "user", "content": message.content}
            )
    print("최근 메시지 로드 완료.")

    for user in user_messages:
        user_messages[user] = list(reversed(user_messages[user]))


def send_to_chatgpt(messages, model="gpt-4o-mini-2024-07-18", temperature=0.5):
    response = clientGPT.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=500,
        temperature=temperature,
    )
    message = response.choices[0].message.content
    print(message)
    messages.append(response.choices[0].message)
    return message


client.run(DISCORD_TOKEN)
