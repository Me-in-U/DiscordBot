import json
from datetime import datetime, time, timedelta, timezone

from discord.ext import commands, tasks

from requests_gpt import image_analysis, send_to_chatgpt
from requests_riot import get_rank_data


class QuestionCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("QuestionCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> QuestionCommands Cog : on ready!")

    @commands.command(
        aliases=["질문"],
        help="ChatGPT에게 질문합니다. '!질문 [질문 내용]' 형식으로 사용하세요.",
    )
    async def question(self, ctx):
        """
        커맨드 질문 처리
        ChatGPT
        """

        target_message = ctx.message.content
        image_url = None

        # 이미지 첨부 확인
        if ctx.message.attachments:
            image_url = ctx.message.attachments[0].url

        self.bot.USER_MESSAGES[ctx.author].append(
            {"role": "user", "content": ctx.message.content}
        )

        # ChatGPT에 메시지 전달
        messages = [
            {
                "role": "developer",
                "content": (
                    "질문에 대한 답을 해라. "
                    "추가적인 질문요청, 궁금한점이 있는지 물어보지 마라. "
                    "질문에만 답해라. "
                    "누가 질문했는지는 언급하지마라."
                ),
            },
            {
                "role": "developer",
                "content": (
                    "내용을 참고하도록 하고 맨 마지막이 질문이다. "
                    "전체 대화 내용이 필요한 질문이면 밑에서 참고해라"
                    "다음은 유저가 말했던 기록이다. "
                    f"전체 대화 내용 : {self.bot.USER_MESSAGES}"
                ),
            },
            {
                "role": "user",
                "content": f"{ctx.author}의 질문 : {target_message}",
            },
            {
                "role": "developer",
                "content": f"아래는 닉네임 정보:\n{self.bot.NICKNAMES}\n",
            },
        ]

        # 이미지 처리 여부
        if image_url:
            response = image_analysis(
                messages, model="gpt-4o", image_url=image_url, temperature=0.4
            )
        else:
            response = send_to_chatgpt(messages, model="gpt-4o", temperature=0.4)

        # 봇 응답 기록
        self.bot.USER_MESSAGES[ctx.author].append(
            {"role": "assistant", "content": response}
        )
        await ctx.reply(f"{response}")

    @commands.command(
        aliases=["신이시여", "신이여", "창섭님"],
        help="정상화의 신에게 질문합니다. '!신이시여 [질문 내용]' 형식으로 사용하세요.",
    )
    async def to_god(self, ctx):
        """
        커맨드 질문 처리
        ChatGPT
        """

        target_message = ctx.message.content
        image_url = None

        # 이미지 첨부 확인
        if ctx.message.attachments:
            image_url = ctx.message.attachments[0].url

        self.bot.USER_MESSAGES[ctx.author].append(
            {"role": "user", "content": ctx.message.content}
        )

        # ChatGPT에 메시지 전달
        messages = [
            {
                "role": "developer",
                "content": (
                    "당신은 세계 최고 정상화의 신, 게임 메이플스토리의 신창섭 디렉터이다. "
                    "당신은 모든것을 정상화 하는 능력이 있다. "
                    "신으로써 아래 질문에 대한 답을 해야한다."
                    "당신은 모든것을 알고있다. 이에 답을하라. "
                    "정상화의 신이 말하는 말투로 말해라."
                    "문제가 있다면 해결하는 방향으로 정상화 시켜라."
                    "아래는 유저가 말했던 기록이다. 내용을 참고하도록 하고 맨 마지막이 질문이다."
                ),
            },
            {
                "role": "developer",
                "content": f"전체 대화 내용 : {self.bot.USER_MESSAGES}",
            },
            {
                "role": "user",
                "content": f"{ctx.author}의 질문 : {target_message}",
            },
            {
                "role": "developer",
                "content": f"아래는 닉네임 정보:\n{self.bot.NICKNAMES}\n",
            },
        ]

        # 이미지 처리 여부
        if image_url:
            response = image_analysis(
                messages, model="gpt-4o", image_url=image_url, temperature=0.7
            )
        else:
            response = send_to_chatgpt(messages, model="gpt-4o", temperature=0.7)

        # 봇 응답 기록
        self.bot.USER_MESSAGES[ctx.author].append(
            {"role": "assistant", "content": response}
        )
        await ctx.reply(f"{response}")

    @commands.command(
        aliases=["요약"],
        help="채팅 내용을 요약합니다다. '!요약",
    )
    async def summary(self, ctx, *, text: str = None):
        """
        커맨드 요약 처리리
        오늘의 메시지 전체 요약
        """
        # 저장된 모든 대화 기록 확인
        if not self.bot.USER_MESSAGES:
            await ctx.reply("**요약할 대화 내용이 없습니다.**")
            return

        request_message = text if text else ""

        # 요약 요청 메시지 생성
        messages = [
            {
                "role": "developer",
                "content": (
                    "당신은 요약 전문가입니다. "
                    "주어진 대화 내용을 요약해주세요. "
                    "전체적인 내용을 3줄 이내로 요약. "
                    "그 이후 각 유저가 한 말을 따로 요약한걸 추가해줘. "
                    "닉네임 : 요약 형식으로. "
                    "자연스러운 말투로 말해줘. "
                    "추가 요청 사항이 있다면 위 내용보다 우선 처리 해줘줘"
                    "대화에 참여하지 않은 유저는 알려주지마"
                ),
            },
            {"role": "developer", "content": f"추가 요청 사항 : {request_message}"},
            {
                "role": "developer",
                "content": f"아래 채팅 내용을 요약해 주세요:\n{self.bot.USER_MESSAGES}\n",
            },
            {
                "role": "developer",
                "content": f"아래는 닉네임 정보:\n{self.bot.NICKNAMES}\n",
            },
        ]

        # ChatGPT에 메시지 전달
        response = send_to_chatgpt(messages, model="gpt-4o", temperature=0.6)

        # 응답 출력
        await ctx.reply(f"{response}")

    @commands.command(
        aliases=["번역", "버녁"],
        help="이전 채팅 내용을 한국어로 번역하거나 '!번역 [문장]' 형식으로 번역합니다.",
    )
    async def translate(self, ctx, *, text: str = None):
        """
        입력된 문장이 있으면 해당 문장을, 없으면 최근 메시지를 번역합니다.
        """
        target_message = None
        image_url = None

        if text:
            # 명령어 뒤에 입력된 문장이 있을 경우 해당 문장 번역
            target_message = text.strip()
        else:
            # 최근 메시지 탐색
            async for message in ctx.channel.history(limit=10):  # 최근 최대 10개 탐색
                if message.author != self.bot.user and message.id != ctx.message.id:
                    target_message = message.content
                    # 이미지 첨부 여부 확인
                    if message.attachments:
                        image_url = message.attachments[0].url
                    break
            else:
                # 번역할 메시지가 없을 경우
                await ctx.reply("**번역할 메시지를 찾지 못했습니다.**")
                return

        # 번역 요청 메시지 생성
        messages = [
            {
                "role": "developer",
                "content": (
                    "당신은 전문 번역가입니다. "
                    "대화 내용을 직역보다는 자연스럽게 한국어로 번역해 주세요. "
                    "번역된 문장 이외에 추가적인 설명은 필요 없습니다."
                ),
            },
            {
                "role": "developer",
                "content": f"아래는 번역할 대화 내용입니다:\n{target_message}",
            },
        ]

        # 이미지 처리 여부
        if image_url:
            translated_message = image_analysis(
                messages, model="gpt-4o", image_url=image_url, temperature=0.5
            )
        else:
            translated_message = send_to_chatgpt(
                messages, model="gpt-4o", temperature=0.5
            )

        # 번역 결과 출력
        await ctx.reply(translated_message)

    @commands.command(
        aliases=["해석"],
        help="이전 채팅 내용을 해석하거나 '!해석 [문장]' 형식으로 해석합니다.",
    )
    async def interpret(self, ctx, *, text: str = None):
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
                if message.author != self.bot.user and message.id != ctx.message.id:
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
                "role": "developer",
                "content": (
                    "당신은 문장 해석 전문가입니다. "
                    "대화 내용의 의미나 숨겨진 뜻이 있을것 같으면 찾아서 해석해주세요."
                ),
            },
            {
                "role": "developer",
                "content": f"아래는 해석할 대화 내용입니다:\n{target_message}",
            },
        ]

        if image_url:
            # 이미지와 텍스트를 처리
            interpreted = image_analysis(
                messages, model="gpt-4o", image_url=image_url, temperature=0.6
            )
        else:
            # 텍스트만 처리
            interpreted = send_to_chatgpt(messages, model="gpt-4o", temperature=0.6)

        # 번역 결과 출력
        await ctx.reply(interpreted)


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(QuestionCommands(bot))
    print("QuestionCommands Cog : setup 완료!")
