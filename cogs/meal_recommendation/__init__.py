import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import generate_text_model


MEAL_RECOMMENDATION_MODEL = "gpt-5.4-nano"
MEAL_RECOMMENDATION_MAX_OUTPUT_TOKENS = 24
MEAL_RECOMMENDATION_ERROR_MESSAGE = "⚠️ 음식 추천 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
MEAL_RECOMMENDATION_INPUT = "지금 먹을 음식 메뉴 하나를 한국어로 추천해줘."
MEAL_RECOMMENDATION_INSTRUCTIONS = (
    "한식, 중식, 일식, 양식, 동남아, 남아시아, 중동, 지중해, "
    "남미, 멕시코, 유럽, 아프리카 등 세계 여러 음식 문화권을 폭넓게 고려한다. "
    "특정 국가, 지역, 음식 분류에 반복적으로 치우치지 않는다. "
    "음식 메뉴명 하나만 출력한다. "
    "설명, 분류, 국가명, 문장, 이모지, 번호, 따옴표, 마침표, Markdown heading은 출력하지 않는다."
)

logger = logging.getLogger(__name__)


def format_meal_recommendation_response(model_output: str | None) -> str:
    menu = _extract_menu_name(model_output)
    if not menu:
        return ""
    return f"# {menu}"


def build_meal_recommendation_input(previous_menu: str | None = None) -> str:
    if not previous_menu:
        return MEAL_RECOMMENDATION_INPUT
    return (
        f'{MEAL_RECOMMENDATION_INPUT}\n'
        f'직전 추천 메뉴는 "{previous_menu}"이다. 이번에는 반드시 다른 메뉴를 추천해라.'
    )


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
        self._last_recommended_menus: dict[str, str] = {}
        print("MealRecommendationCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> MealRecommendationCommands Cog : on ready!")

    @app_commands.command(name="뭐먹지", description="음식 메뉴 하나를 추천합니다.")
    async def recommend_meal(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        state_key = self._recommendation_state_key(interaction)
        previous_menu = self._last_recommended_menus.get(state_key)

        try:
            menu = await self._generate_menu(previous_menu)
            if previous_menu and menu == previous_menu:
                menu = await self._generate_menu(previous_menu)

            if not menu or (previous_menu and menu == previous_menu):
                raise ValueError("OpenAI returned an empty or repeated meal recommendation.")

            self._last_recommended_menus[state_key] = menu
            response = format_meal_recommendation_response(menu)
        except Exception:
            logger.exception("음식 메뉴 추천 중 오류가 발생했습니다.")
            response = MEAL_RECOMMENDATION_ERROR_MESSAGE

        try:
            await interaction.followup.send(response)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("음식 메뉴 추천 응답 전송 실패", exc_info=True)

    async def _generate_menu(self, previous_menu: str | None) -> str:
        model_output = await asyncio.to_thread(
            generate_text_model,
            user_input=build_meal_recommendation_input(previous_menu),
            instructions=MEAL_RECOMMENDATION_INSTRUCTIONS,
            model=MEAL_RECOMMENDATION_MODEL,
            max_output_tokens=MEAL_RECOMMENDATION_MAX_OUTPUT_TOKENS,
            reasoning_effort="none",
            text_verbosity="low",
        )
        return _extract_menu_name(model_output)

    def _recommendation_state_key(self, interaction: discord.Interaction) -> str:
        guild_id = getattr(interaction, "guild_id", None)
        if guild_id is not None:
            return f"guild:{int(guild_id)}"

        user = getattr(interaction, "user", None)
        user_id = getattr(user, "id", None)
        if user_id is not None:
            return f"user:{int(user_id)}"

        return "global"


async def setup(bot: commands.Bot):
    await bot.add_cog(MealRecommendationCommands(bot))
    print("MealRecommendationCommands Cog : setup 완료!")
