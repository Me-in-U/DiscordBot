import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model
from common.openai_prompt import build_prompt, build_single_image_content
from util.logging_utils import log_user_error


SEARCH_PROMPT_ID = "pmpt_68b25c89c1a48193a60de5a3cb23a1eb0c25a13613efd1bf"
SEARCH_PROMPT_VERSION = "12"
logger = logging.getLogger(__name__)


class SearchCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("SearchCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> SearchCommands Cog : on ready!")

    @app_commands.command(
        name="검색",
        description="텍스트와 선택 이미지를 근거로 최신 정보를 검색합니다.",
    )
    @app_commands.rename(text="검색어", image="이미지")
    @app_commands.describe(
        text="검색할 내용을 입력하세요.",
        image="검색 단서로 사용할 이미지를 첨부하세요. (선택)",
    )
    async def search(
        self,
        interaction: discord.Interaction,
        text: str,
        image: discord.Attachment | None = None,
    ):
        # 슬래시 커맨드 응답을 대기 상태로 둡니다.
        await interaction.response.defer(thinking=True)

        try:
            response = await asyncio.to_thread(
                custom_prompt_model,
                image_content=build_single_image_content(
                    image.url if image else None
                ),
                prompt=build_prompt(
                    SEARCH_PROMPT_ID,
                    SEARCH_PROMPT_VERSION,
                    {"user_input": text.strip()},
                ),
            )
        except Exception as exc:
            response = log_user_error(logger, "검색", exc)

        try:
            await interaction.followup.send(response)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("검색 결과 전송 실패", exc_info=True)


async def setup(bot):
    await bot.add_cog(SearchCommands(bot))
    print("SearchCommands Cog : setup 완료!")
