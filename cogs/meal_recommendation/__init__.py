import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import generate_text_model


MEAL_RECOMMENDATION_MODEL = "gpt-5.4-nano"
MEAL_RECOMMENDATION_MAX_OUTPUT_TOKENS = 24
MEAL_RECOMMENDATION_FALLBACK = "김치볶음밥"
MEAL_RECOMMENDATION_INPUT = "지금 먹을 음식 메뉴 하나를 한국어로 추천해줘."
MEAL_RECOMMENDATION_INSTRUCTIONS = (
    "음식 메뉴 하나만 추천한다. 반드시 메뉴명만 출력한다. "
    "문장, 설명, 이모지, 번호, 따옴표, 마침표, Markdown heading은 출력하지 않는다."
)

logger = logging.getLogger(__name__)


def format_meal_recommendation_response(model_output: str | None) -> str:
    menu = _extract_menu_name(model_output)
    return f"# {menu or MEAL_RECOMMENDATION_FALLBACK}"


def _extract_menu_name(model_output: str | None) -> str:
    if not model_output:
        return ""

    for raw_line in str(model_output).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue

        line = line.lstrip("#").strip()
        line = re.sub(r"^\d+[\.)]\s*", "", line)
        line = line.lstrip("-*•").strip()
        line = line.strip("`\"'“”‘’")
        line = line.strip().rstrip(".。!！?？")
        if line:
            return line

    return ""


class MealRecommendationCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("MealRecommendationCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> MealRecommendationCommands Cog : on ready!")

    @app_commands.command(name="뭐먹지", description="음식 메뉴 하나를 추천합니다.")
    async def recommend_meal(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            model_output = await asyncio.to_thread(
                generate_text_model,
                user_input=MEAL_RECOMMENDATION_INPUT,
                instructions=MEAL_RECOMMENDATION_INSTRUCTIONS,
                model=MEAL_RECOMMENDATION_MODEL,
                max_output_tokens=MEAL_RECOMMENDATION_MAX_OUTPUT_TOKENS,
                reasoning_effort="none",
                text_verbosity="low",
            )
            response = format_meal_recommendation_response(model_output)
        except Exception:
            logger.exception("음식 메뉴 추천 중 오류가 발생했습니다.")
            response = format_meal_recommendation_response(None)

        try:
            await interaction.followup.send(response)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("음식 메뉴 추천 응답 전송 실패", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MealRecommendationCommands(bot))
    print("MealRecommendationCommands Cog : setup 완료!")
