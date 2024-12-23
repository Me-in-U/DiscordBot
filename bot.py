import json
import os
from datetime import datetime, time, timedelta, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from clientGPT import send_to_chatgpt
from riot import get_rank_data

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("MY_CHANNEL_ID"))

# settingData 파일 이름
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTING_DATA = os.path.join(BASE_DIR, "settingData.json")

# Client 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="!", intents=intents)
client.remove_command("help")


# 유저별 채팅팅 저장용 딕셔너리
user_messages = {}

# 유저 닉네임 저장
nicknames = {}

# 서울 시간대 설정 (UTC+9)
seoul_tz = timezone(timedelta(hours=9))


# 일일 랭크 유저 정보
game_name = ""
tag_line = ""
daily_rank_loop = True


#! client.event
@client.event
async def on_ready():
    """
    봇 실행 준비.
    """
    print(f"Logged on as {client.user}!")
    await load_json()  # settingData.json 로드
    await load_all_nicknames()  # 채널의 모든 멤버 닉네임 저장
    await load_recent_messages()  # 최근 메시지 로드
    await update_presence()

    reset_user_messages.start()  # 자정 루프 시작
    presence_update_task.start()  # 1분마다 Presence 업데이트 태스크 시작
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
    aliases=["신이시여", "신이여", "창섭님"],
    help="정상화의 신에게 질문합니다. '!신이시여 [질문 내용]' 형식으로 사용하세요.",
)
async def to_god(ctx, *, text: str = None):
    """
    커맨드 질문 처리
    ChatGPT
    """
    message = text.strip() if text else ""

    messages = [
        {
            "role": "system",
            "content": "당신은 세계 최고 정상화의 신, 신창섭 디렉터이다. 당신은 모든것을 정상화 하는 능력이 있다. 신으로써 아래 질문에 대한 답을 해야한다. 당신은 모든것을 알고있다. 이에 답을하라",
        },
        {
            "role": "system",
            "content": "정상화의 신이 말하는 말투로 말해라. 문제가 있다면 해결하는 방향으로 정상화 시켜라",
        },
        {
            "role": "user",
            "content": message,
        },
    ]
    # ChatGPT에 메시지 전달
    response = send_to_chatgpt(messages, temperature=0.7)
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

    request_message = text.strip() if text else ""

    # 요약 요청 메시지 생성
    messages = [
        {
            "role": "system",
            "content": "당신은 요약 전문가입니다. 주어진 대화 내용을 요약해주세요. ",
        },
        {
            "role": "system",
            "content": """전체적인 내용을 5줄 이내로 요약. 
            그 이후 각 유저가 한 말을 따로 요약한걸 추가해줘 
            닉네임 : 요약 형식으로 """,
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
        target_message = text.strip()
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


@client.command(aliases=["솔랭"], help="")
async def print_solo_rank(ctx, *, text: str = None):
    """
    봇의 명령어 목록과 설명을 출력합니다.
    """
    text = text.strip()
    game_name = text.split("#")[0]
    tag_line = text.split("#")[1]

    # 명령어 출력
    await ctx.reply(print_rank_data(get_rank_data(game_name, tag_line, "solo")))


@client.command(aliases=["자랭"], help="")
async def print_flex_rank(ctx, *, text: str = None):
    """
    봇의 명령어 목록과 설명을 출력합니다.
    """
    game_name = text.split("#")[0]
    tag_line = text.split("#")[1]

    # 명령어 출력
    await ctx.reply(print_rank_data(get_rank_data(game_name, tag_line, "flex")))


@client.command(
    aliases=["일일랭크"],
    help="자정 솔랭 출력 정보를 출력합니다",
)
async def daily_rank(ctx):
    """
    현재 설정된 일일 랭크 정보를 출력합니다.
    """
    # 변경 성공 메시지
    await ctx.reply(
        f"✅ **현재 일일솔로랭크 출력 예정 정보**\n- 닉네임: {game_name}\n- 태그: {tag_line}"
    )


@client.command(
    aliases=["일일랭크변경"],
    help="자정 솔랭 출력 닉네임#태그를 업데이트합니다.",
)
async def update_daily_rank(ctx, *, text: str = None):
    """
    game_name과 tag_line을 업데이트하고 JSON 파일에 저장한 후 알림을 보냅니다.
    """
    global game_name, tag_line  # 기존 변수를 수정할 수 있도록 global 선언

    try:
        # 명령어에서 새로운 game_name과 tag_line 추출
        if text and "#" in text:
            new_game_name, new_tag_line = text.strip().split("#")
        else:
            await ctx.reply(
                "**올바른 형식으로 입력해주세요. 예: !일일랭크변경 닉네임#태그**"
            )
            return

        # JSON 파일 업데이트
        with open(SETTING_DATA, "r", encoding="utf-8") as file:
            settings = json.load(file)
        settings["dailySoloRank"]["userData"]["game_name"] = new_game_name
        settings["dailySoloRank"]["userData"]["tag_line"] = new_tag_line
        with open(SETTING_DATA, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=4)

        # 변수 업데이트
        game_name, tag_line = new_game_name, new_tag_line

        # 변경 성공 메시지
        await ctx.reply(
            f"✅ **성공적으로 업데이트되었습니다.**\n새 값:\n- 닉네임: {game_name}\n- 태그: {tag_line}"
        )
    except Exception as e:
        await ctx.reply(f"⚠️ **업데이트 중 오류가 발생했습니다.**\n{str(e)}")


@client.command(
    aliases=["일일랭크루프"],
    help="자정 루프 실행 여부를 설정합니다. 예: !일일랭크루프 true/false",
)
async def toggle_daily_loop(ctx, *, status: str = None):
    """
    자정 루프 실행 여부를 설정합니다.
    """
    global daily_rank_loop

    try:
        if status is None or status.lower() not in ["true", "false"]:
            await ctx.reply(
                "**올바른 형식으로 입력해주세요. 예: !일일랭크루프 true/false**"
            )
            return

        # JSON 파일 업데이트
        new_loop_status = status.lower() == "true"
        with open(SETTING_DATA, "r", encoding="utf-8") as file:
            settings = json.load(file)
        settings["dailySoloRank"]["loop"] = new_loop_status
        with open(SETTING_DATA, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=4)

        # 변수 업데이트
        daily_rank_loop = new_loop_status

        # 변경 성공 메시지
        await ctx.reply(
            f"✅ **루프 상태가 {'활성화' if daily_rank_loop else '비활성화'}로 변경되었습니다.**"
        )
    except Exception as e:
        await ctx.reply(f"⚠️ **루프 상태 변경 중 오류가 발생했습니다.**\n{str(e)}")


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
    if daily_rank_loop:
        await target_channel.send("📢 새로운 하루가 시작됩니다. 일일 솔랭 정보 출력")
        await target_channel.send(
            print_rank_data(get_rank_data(game_name, tag_line, "solo"))
        )
    else:
        await target_channel.send("📢 새로운 하루가 시작됩니다.")


@tasks.loop(minutes=1)
async def presence_update_task():
    """
    1분마다 Discord 봇 상태(Presence)를 갱신합니다.
    """
    await update_presence()


#! def
async def load_json():
    global game_name, tag_line, daily_rank_loop
    # JSON 파일에서 닉네임 로드
    print("-------------------- 설정 로드 --------------------")
    with open(SETTING_DATA, "r", encoding="utf-8") as file:
        settings = json.load(file)
        game_name = (
            settings.get("dailySoloRank", {}).get("userData", {}).get("game_name")
        )
        tag_line = settings.get("dailySoloRank", {}).get("userData", {}).get("tag_line")
        daily_rank_loop = settings.get("dailySoloRank", {}).get("loop", True)
        if game_name and tag_line:
            print(f"랭크 검색할 닉네임 로드: {game_name}#{tag_line}")
        else:
            print("JSON 파일에서 닉네임 데이터를 로드하지 못했습니다.")
            game_name, tag_line = None, None
        print(
            f"일일 랭크 출력 루프 상태: {'활성화' if daily_rank_loop else '비활성화'}"
        )
    print("---------------------------------------------------\n")


async def load_all_nicknames():
    """
    채널에 있는 모든 멤버의 닉네임을 저장합니다.
    """
    # 봇이 참여한 모든 길드(서버) 확인
    print("------------------- 닉네임 로드 -------------------")
    for guild in client.guilds:
        print(f"서버 '{guild.name}'에서 멤버 목록을 불러옵니다...")
        for member in guild.members:
            nicknames[member] = (
                member.display_name if member.display_name else member.name
            )
    print("---------------------------------------------------\n")


async def load_recent_messages():
    target_channel = client.get_channel(CHANNEL_ID)
    print("------------------- 메시지 로드 -------------------")
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
    print("---------------------------------------------------\n")

    for user in user_messages:
        user_messages[user] = list(reversed(user_messages[user]))


async def update_presence():
    """
    Discord 봇 상태(Presence)를 업데이트합니다.
    """
    total_messages = sum(len(msg_list) for msg_list in user_messages.values())
    # 천 단위로 콤마 추가
    formatted_total_messages = f"{total_messages:,}"
    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name=f"!도움 | {formatted_total_messages}개의 채팅 메시지",
    )
    await client.change_presence(activity=activity)


def print_rank_data(data):
    return (
        f'## "{data["game_name"]}#{data["tag_line"]}" {data["rank_type_kor"]} 정보\n'
        f"티어: {data['tier']} {data['rank']} {data['league_points']}포인트\n"
        f"승리: {data['wins']} ({data['win_rate']:.2f}%)\n"
        f"패배: {data['losses']}"
    )


client.run(DISCORD_TOKEN)
