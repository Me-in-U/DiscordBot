from discord.ext import commands

from api.chatGPT import general_purpose_model


class SummarizeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("SummarizeCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> SummarizeCommands Cog : on ready!")

    @commands.command(
        aliases=["요약"],
        help="채팅 내용을 요약합니다다. '!요약",
    )
    async def summary(self, ctx, *, text: str = None):
        """
        커맨드 요약 처리
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
            {
                "role": "developer",
                "content": (
                    "다음은 유저가 말했던 기록이다. 채팅 내용을 요약해라."
                    f"전체 대화 내용: {self.bot.USER_MESSAGES}\n\n"
                    f"닉네임 정보:{self.bot.NICKNAMES}\n"
                ),
            },
            {
                "role": "developer",
                "content": f"요약 추가 요청 사항 : {request_message}",
            },
        ]

        # ChatGPT에 메시지 전달
        try:
            response = general_purpose_model(
                messages, model="gpt-4o-mini", temperature=0.4
            )
        except Exception as e:
            response = f"Error: {e}"

        # 응답 출력
        await ctx.reply(f"{response}")


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(SummarizeCommands(bot))
    print("SummarizeCommands Cog : setup 완료!")
