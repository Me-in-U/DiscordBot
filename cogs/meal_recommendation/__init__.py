import asyncio
import logging
import random
import re
from collections import deque

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model
from common.openai_prompt import build_prompt


MEAL_RECOMMENDATION_PROMPT_ID = "pmpt_6ac5ae2d5b98819382e307d2853394010028d27bf97a5ecd"
MEAL_RECOMMENDATION_PROMPT_VERSION = "1"
MEAL_RECOMMENDATION_ERROR_MESSAGE = "⚠️ 음식 추천 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
MEAL_RECOMMENDATION_CUISINES = (
    "한식", "중식", "일식", "이탈리아", "프랑스", "스페인",
    "그리스와 지중해", "튀르키예와 중동", "인도와 남아시아",
    "태국", "베트남", "인도네시아와 말레이시아", "멕시코",
    "남미", "미국", "아프리카", "독일과 동유럽",
)

logger = logging.getLogger(__name__)


def format_meal_recommendation_response(model_output: str | None) -> str:
    menu = _extract_menu_name(model_output)
    if not menu:
        return ""
    return f"# {menu}"


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
        # ponytail: process-local history resets on restart; use setting_data if persistence is needed.
        self._recent_menus: dict[str, deque[str]] = {}
        self._remaining_cuisines: dict[str, list[str]] = {}
        print("MealRecommendationCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> MealRecommendationCommands Cog : on ready!")

    @app_commands.command(name="뭐먹지", description="음식 메뉴 하나를 추천합니다.")
    async def recommend_meal(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        state_key = self._recommendation_state_key(interaction)
        recent_menus = self._recent_menus.setdefault(state_key, deque(maxlen=20))
        cuisines = self._remaining_cuisines.setdefault(state_key, [])
        if not cuisines:
            cuisines.extend(MEAL_RECOMMENDATION_CUISINES)
            random.shuffle(cuisines)
        cuisine = cuisines.pop()

        try:
            menu = await self._generate_menu(cuisine, recent_menus)
            if menu in recent_menus:
                menu = await self._generate_menu(cuisine, recent_menus)

            if not menu or menu in recent_menus:
                raise ValueError("OpenAI returned an empty or repeated meal recommendation.")

            recent_menus.append(menu)
            response = format_meal_recommendation_response(menu)
        except Exception:
            logger.exception("음식 메뉴 추천 중 오류가 발생했습니다.")
            response = MEAL_RECOMMENDATION_ERROR_MESSAGE

        try:
            await interaction.followup.send(response)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("음식 메뉴 추천 응답 전송 실패", exc_info=True)

    async def _generate_menu(self, cuisine: str, recent_menus: deque[str]) -> str:
        model_output = await asyncio.to_thread(
            custom_prompt_model,
            prompt=build_prompt(
                MEAL_RECOMMENDATION_PROMPT_ID,
                MEAL_RECOMMENDATION_PROMPT_VERSION,
                {
                    "cuisine": cuisine,
                    "recent_menus": "\n".join(recent_menus) or "없음",
                    "selection_seed": str(random.getrandbits(64)),
                },
            ),
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
