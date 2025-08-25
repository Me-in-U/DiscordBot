import discord
from discord import app_commands
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

    @app_commands.command(name="요약", description="채팅 내용을 요약합니다.")
    @app_commands.describe(
        추가_요청="추가로 원하는 요약 사항이 있으면 입력하세요. (선택)"
    )
    async def summary(
        self, interaction: discord.Interaction, 추가_요청: str | None = None
    ):
        """
        커맨드 요약 처리
        오늘의 메시지 전체 요약
        """
        # 저장된 모든 대화 기록 확인
        if not self.bot.USER_MESSAGES:
            await interaction.response.send_message("**요약할 대화 내용이 없습니다.**")
            return

        # 최초 응답: "요약 중..." 메시지를 보냅니다.
        await interaction.response.send_message("요약 중...", ephemeral=False)

        # 요약 요청 메시지 생성
        request_message = 추가_요청 or ""
        messages = [
            {
                "role": "developer",
                "content": (
                    "당신은 요약 전문가입니다. "
                    "주어진 대화 내용을 요약해주세요. "
                    "전체적인 내용을 3줄 이내로 요약. "
                    "그 이후 각 유저가 한 말을 따로 요약한걸 추가해줘. "
                    "유저이름 : 요약 형식으로. "
                    "자연스러운 말투로 말해줘. "
                    "추가 요청 사항이 있다면 위 내용보다 우선 처리 해줘줘"
                    "대화에 참여하지 않은 유저는 알려주지마"
                ),
            },
            {
                "role": "developer",
                "content": (
                    "다음은 유저가 말했던 최근 150개의 기록이다. 채팅 내용을 요약해라."
                    f"전체 대화 내용: {self.bot.USER_MESSAGES[-150:]}\n\n"
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
                messages, model="gpt-5-mini", temperature=0.4
            )
        except Exception as e:
            response = f"Error: {e}"

        # 응답 출력
        sent_msg = await interaction.original_response()
        await sent_msg.edit(content=response)


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(SummarizeCommands(bot))
    print("SummarizeCommands Cog : setup 완료!")
