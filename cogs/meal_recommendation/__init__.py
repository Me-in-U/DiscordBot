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
MEAL_RECOMMENDATION_PROMPT_VERSION = "2"
MEAL_RECOMMENDATION_ERROR_MESSAGE = "⚠️ 음식 추천 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
MEAL_RECOMMENDATION_CATEGORIES = {
    "한식": ("제육덮밥", "불고기덮밥", "비빔밥", "오므라이스", "오징어덮밥", "낙지덮밥"),
    "찜/탕/찌개": ("김치찌개", "된장찌개", "순두부찌개", "부대찌개", "찜닭", "김치찜"),
    "국밥/국수": ("순대국밥", "돼지국밥", "뼈해장국", "설렁탕", "물냉면", "칼국수"),
    "분식": ("떡볶이", "로제떡볶이", "라볶이", "참치김밥", "쫄면", "잔치국수"),
    "치킨": ("후라이드치킨", "양념치킨", "간장치킨", "마늘치킨", "숯불양념치킨", "닭강정"),
    "피자": ("페퍼로니피자", "불고기피자", "콤비네이션피자", "고구마피자", "포테이토피자", "치즈피자"),
    "버거": ("치즈버거", "불고기버거", "치킨버거", "새우버거", "베이컨버거", "더블패티버거"),
    "중식": ("짜장면", "짬뽕", "중화볶음밥", "탕수육", "마라탕", "마라샹궈"),
    "돈까스": ("돈까스", "치즈돈까스", "안심돈까스", "등심돈까스", "생선까스", "카레돈까스"),
    "일식": ("라멘", "우동", "가츠동", "규동", "일본식카레", "메밀소바"),
    "회/해물": ("모둠초밥", "연어초밥", "광어회", "물회", "회덮밥", "꼬막비빔밥"),
    "족발/보쌈": ("족발", "보쌈", "불족발", "마늘족발", "냉채족발", "마늘보쌈"),
    "고기/구이": ("삼겹살구이", "돼지갈비", "닭갈비", "곱창볶음", "막창구이", "오리불고기"),
    "양식": ("토마토파스타", "크림파스타", "로제파스타", "알리오올리오", "새우리조또", "함박스테이크"),
    "아시안": ("소고기쌀국수", "분짜", "팟타이", "나시고랭", "월남쌈", "치킨커리"),
    "도시락/죽": ("치킨마요도시락", "제육도시락", "불고기도시락", "전복죽", "소고기야채죽", "참치야채죽"),
    "샐러드/샌드위치": ("닭가슴살샐러드", "연어샐러드", "연어포케", "참치샌드위치", "에그샌드위치", "햄치즈토스트"),
}

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
        # shortcut: process-local history resets on restart; use setting_data if persistence is needed.
        self._recent_menus: dict[str, deque[str]] = {}
        self._remaining_cuisines: dict[str, list[str]] = {}
        print("MealRecommendationCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> MealRecommendationCommands Cog : on ready!")

    @app_commands.command(name="뭐먹지", description="한국 배달앱에서 흔히 주문하는 식사 메뉴 하나를 추천합니다.")
    async def recommend_meal(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        state_key = self._recommendation_state_key(interaction)
        recent_menus = self._recent_menus.setdefault(state_key, deque(maxlen=20))
        cuisines = self._remaining_cuisines.setdefault(state_key, [])
        if not cuisines:
            cuisines.extend(MEAL_RECOMMENDATION_CATEGORIES)
            random.shuffle(cuisines)
        cuisine = cuisines.pop()

        try:
            menu = await self._generate_menu(cuisine, recent_menus)
            if not menu or menu in recent_menus:
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
                    "cuisine": f"{cuisine}\n허용 메뉴: {' | '.join(MEAL_RECOMMENDATION_CATEGORIES[cuisine])}",
                    "recent_menus": "\n".join(recent_menus) or "없음",
                    "selection_seed": str(random.getrandbits(64)),
                },
            ),
        )
        menu = _extract_menu_name(model_output)
        return menu if any(menu in menus for menus in MEAL_RECOMMENDATION_CATEGORIES.values()) else ""

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
