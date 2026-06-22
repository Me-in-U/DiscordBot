import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model
from common.openai_prompt import build_prompt, build_single_image_content
from util.message.recent import get_recent_messages
from util.logging_utils import log_user_error


GENERAL_PROMPT_ID = "pmpt_68ac254fa8008190861e8f3f686556d50c6160cd272b9aca"
GENERAL_PROMPT_VERSION = "4"
GOD_QUESTION_PROMPT_ID = "pmpt_68acfa93ac6481959537fcb1853c883307d25e6bf62ef36c"
GOD_QUESTION_PROMPT_VERSION = "5"
logger = logging.getLogger(__name__)


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
    @app_commands.rename(text="질문", image="이미지")
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

        try:
            response = await asyncio.to_thread(
                custom_prompt_model,
                image_content=build_single_image_content(image_url),
                prompt=build_prompt(
                    GENERAL_PROMPT_ID,
                    GENERAL_PROMPT_VERSION,
                    {
                        "recent_messages": get_recent_messages(
                            client=self.bot, guild_id=interaction.guild.id, limit=20
                        ),
                        "user_name": interaction.user.name,
                        "question": text.strip(),
                    },
                ),
            )
        except Exception as exc:
            response = log_user_error(logger, "질문", exc)

        try:
            await interaction.followup.send(f"{response}")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("질문 응답 전송 실패", exc_info=True)

    @app_commands.command(
        name="신이시여",
        description="정상화의 신에게 질문합니다. 질문 내용과 이미지를 함께 입력할 수 있습니다.",
    )
    @app_commands.rename(text="질문", image="이미지")
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

        try:
            response = await asyncio.to_thread(
                custom_prompt_model,
                image_content=build_single_image_content(image_url),
                prompt=build_prompt(
                    GOD_QUESTION_PROMPT_ID,
                    GOD_QUESTION_PROMPT_VERSION,
                    {
                        "recent_messages": get_recent_messages(
                            client=self.bot, guild_id=interaction.guild.id, limit=20
                        ),
                        "user_name": interaction.user.name,
                        "question": text.strip(),
                    },
                ),
            )
        except Exception as exc:
            response = log_user_error(logger, "신이시여 질문", exc)

        try:
            await interaction.followup.send(f"{response}")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("신이시여 응답 전송 실패", exc_info=True)


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(QuestionCommands(bot))
    print("QuestionCommands Cog : setup 완료!")
