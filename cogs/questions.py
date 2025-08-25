import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model, text_input


class QuestionCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("QuestionCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> QuestionCommands Cog : on ready!")

    @app_commands.command(
        name="질문",
        description="ChatGPT에게 질문합니다. 텍스트 매개변수로 질문 내용을 입력하세요.",
    )
    @app_commands.describe(text="질문할 내용을 입력하세요.")
    async def question(
        self,
        interaction: discord.Interaction,
        text: str,
        image: discord.Attachment = None,
    ):
        """
        커맨드 질문 처리
        ChatGPT
        """
        # 호출된 슬래시 커맨드 응답을 잠시 대기 상태로 둡니다.
        await interaction.response.defer(thinking=True)

        # 이미지 첨부 확인
        image_url = None
        if image:
            image_url = image.url

        # ChatGPT에 메시지 전달
        messages = None
        if image_url:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                            },
                        },
                    ],
                },
            ]

        try:
            response = custom_prompt_model(
                messages=messages,
                prompt={
                    "id": "pmpt_68ac254fa8008190861e8f3f686556d50c6160cd272b9aca",
                    "version": "1",
                    "variables": {
                        "user_messages": self.bot.USER_MESSAGES[-20:],
                        "user_name": interaction.user.name,
                        "question": text.strip(),
                    },
                },
            )
        except Exception as e:
            response = f"Error: {e}"

        await interaction.followup.send(f"{response}")

    @app_commands.command(
        name="신이시여",
        description="정상화의 신에게 질문합니다. 질문 내용과 이미지를 함께 입력할 수 있습니다.",
    )
    @app_commands.describe(
        text="질문할 내용을 입력하세요.", image="(선택) 질문과 함께 보낼 이미지 첨부"
    )
    async def to_god(
        self,
        interaction: discord.Interaction,
        text: str,
        image: discord.Attachment = None,
    ):
        """
        커맨드 질문 처리
        ChatGPT
        """
        # 호출된 슬래시 커맨드 응답을 잠시 대기 상태로 둡니다.
        await interaction.response.defer(thinking=True)

        # 이미지 첨부 확인
        image_url = None
        if image:
            image_url = image.url

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
                    "채팅 내용에 관한 질문을 한다면 아래 내용을 참고해라"
                    "다음은 모든 유저가 말했던 최근 20개 기록 정보이다.\n"
                    f"전체 대화 내용: {self.bot.USER_MESSAGES[-20:]}\n\n"
                ),
            },
        ]
        if image_url:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{interaction.user.name}의 질문 : {text}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                            },
                        },
                    ],
                },
            )
        else:
            messages.append(
                {
                    "role": "user",
                    "content": f"{interaction.user.name}의 질문 : {text}",
                },
            )

        try:
            response = text_input(messages, model="gpt-5", temperature=0.4)
        except Exception as e:
            response = f"Error: {e}"

        await interaction.followup.send(f"{response}")


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(QuestionCommands(bot))
    print("QuestionCommands Cog : setup 완료!")
