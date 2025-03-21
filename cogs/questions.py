from discord.ext import commands

from api.chatGPT import general_purpose_model, image_analysis


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
                    "전체 대화 내용이 필요한 질문이면 밑에서 참고해라"
                    "다음은 유저가 말했던 기록이다. \n"
                    f"전체 대화 내용 : {self.bot.USER_MESSAGES}"
                ),
            },
            {
                "role": "user",
                "content": f"{ctx.author.name}의 질문 : {target_message}",
            },
            {
                "role": "developer",
                "content": f"아래는 닉네임 정보:\n{self.bot.NICKNAMES}\n",
            },
        ]

        # 이미지 처리 여부
        try:
            if image_url:
                response = image_analysis(
                    messages, model="gpt-4o-mini", image_url=image_url, temperature=0.4
                )
            else:
                response = general_purpose_model(
                    messages, model="gpt-4o-mini", temperature=0.4
                )
        except Exception as e:
            response = f"Error: {e}"

        await ctx.reply(f"{response}")

    @commands.command(
        aliases=["신이시여", "신이여", "창섭님", "창섭아"],
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
                ),
            },
            {
                "role": "developer",
                "content": (
                    "전체 대화 내용이 필요한 질문이면 밑에서 참고해라"
                    "다음은 유저가 말했던 기록이다. \n"
                    f"전체 대화 내용 : {self.bot.USER_MESSAGES}"
                ),
            },
            {
                "role": "user",
                "content": f"{ctx.author.name}의 질문 : {target_message}",
            },
            {
                "role": "developer",
                "content": f"아래는 닉네임 정보:\n{self.bot.NICKNAMES}\n",
            },
        ]

        # 이미지 처리 여부
        try:
            if image_url:
                response = image_analysis(
                    messages, model="gpt-4o-mini", image_url=image_url, temperature=0.7
                )
            else:
                response = general_purpose_model(
                    messages, model="gpt-4o-mini", temperature=0.7
                )
        except Exception as e:
            response = f"Error: {e}"

        await ctx.reply(f"{response}")


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(QuestionCommands(bot))
    print("QuestionCommands Cog : setup 완료!")
