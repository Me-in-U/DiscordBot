import asyncio
import ast
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("OPENAI_KEY", "test-key")


MEAL_RECOMMENDATION_COG_PATH = Path("cogs/meal_recommendation/__init__.py")
LEGACY_MEAL_RECOMMENDATION_COG_PATH = Path("cogs/meal_recommendation.py")
CUSTOM_HELP_PATH = Path("cogs/custom_help/__init__.py")


def _decorator_name(decorator: ast.expr) -> str:
    if isinstance(decorator, ast.Call):
        decorator = decorator.func

    parts: list[str] = []
    while isinstance(decorator, ast.Attribute):
        parts.append(decorator.attr)
        decorator = decorator.value

    if isinstance(decorator, ast.Name):
        parts.append(decorator.id)

    return ".".join(reversed(parts))


class _FakeInteraction:
    def __init__(
        self,
        *,
        guild_id: int | None = 123,
        user_id: int = 456,
    ) -> None:
        self.guild_id = guild_id
        self.user = Mock(id=user_id)
        self.response = Mock()
        self.response.defer = AsyncMock()
        self.followup = Mock()
        self.followup.send = AsyncMock()


async def _immediate_to_thread(func, *args, **kwargs):
    return func(*args, **kwargs)


class MealRecommendationTests(unittest.TestCase):
    def test_meal_recommendation_cog_uses_package_layout(self):
        self.assertTrue(MEAL_RECOMMENDATION_COG_PATH.exists())
        self.assertFalse(LEGACY_MEAL_RECOMMENDATION_COG_PATH.exists())

    def test_meal_recommendation_command_is_exposed_from_package_cog(self):
        tree = ast.parse(MEAL_RECOMMENDATION_COG_PATH.read_text(encoding="utf-8"))
        command_names: set[str] = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if _decorator_name(decorator) != "app_commands.command":
                    continue

                command_name = node.name
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == "name":
                            command_name = ast.literal_eval(keyword.value)
                command_names.add(command_name)

        self.assertIn("뭐먹지", command_names)

    def test_help_mentions_meal_recommendation_command(self):
        help_source = CUSTOM_HELP_PATH.read_text(encoding="utf-8")

        self.assertIn("/뭐먹지", help_source)

    def test_command_sends_single_h1_menu_and_fast_openai_options(self):
        from cogs.meal_recommendation import MealRecommendationCommands

        calls = []

        def fake_custom_prompt_model(*args, **kwargs):
            calls.append((args, kwargs))
            return "# 제육\n설명"

        cog = MealRecommendationCommands(Mock())
        interaction = _FakeInteraction()

        with patch(
            "cogs.meal_recommendation.custom_prompt_model",
            side_effect=fake_custom_prompt_model,
        ):
            with patch(
                "cogs.meal_recommendation.asyncio.to_thread",
                side_effect=_immediate_to_thread,
            ):
                asyncio.run(cog.recommend_meal.callback(cog, interaction))

        interaction.response.defer.assert_awaited_once_with(thinking=True)
        interaction.followup.send.assert_awaited_once_with("# 제육")
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args, ())
        from cogs.meal_recommendation import (
            MEAL_RECOMMENDATION_CUISINES,
            MEAL_RECOMMENDATION_PROMPT_ID,
            MEAL_RECOMMENDATION_PROMPT_VERSION,
        )

        self.assertEqual(kwargs["prompt"]["id"], MEAL_RECOMMENDATION_PROMPT_ID)
        self.assertEqual(kwargs["prompt"]["version"], MEAL_RECOMMENDATION_PROMPT_VERSION)
        variables = kwargs["prompt"]["variables"]
        self.assertIn(variables["cuisine"], MEAL_RECOMMENDATION_CUISINES)
        self.assertEqual(variables["recent_menus"], "없음")
        self.assertTrue(variables["selection_seed"].isdigit())

    def test_command_retries_once_when_model_repeats_previous_menu_for_guild(self):
        from cogs.meal_recommendation import MealRecommendationCommands

        calls = []
        outputs = iter(["제육", "제육", "돈까스"])

        def fake_custom_prompt_model(*args, **kwargs):
            calls.append((args, kwargs))
            return next(outputs)

        cog = MealRecommendationCommands(Mock())
        first_interaction = _FakeInteraction(guild_id=10, user_id=1)
        second_interaction = _FakeInteraction(guild_id=10, user_id=2)

        with patch(
            "cogs.meal_recommendation.custom_prompt_model",
            side_effect=fake_custom_prompt_model,
        ):
            with patch(
                "cogs.meal_recommendation.asyncio.to_thread",
                side_effect=_immediate_to_thread,
            ):
                asyncio.run(cog.recommend_meal.callback(cog, first_interaction))
                asyncio.run(cog.recommend_meal.callback(cog, second_interaction))

        first_interaction.followup.send.assert_awaited_once_with("# 제육")
        second_interaction.followup.send.assert_awaited_once_with("# 돈까스")
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1][1]["prompt"]["variables"]["recent_menus"], "제육")
        self.assertEqual(calls[2][1]["prompt"]["variables"]["recent_menus"], "제육")

    def test_cuisine_cycle_rejects_older_menu_and_keeps_twenty_recent_menus(self):
        from cogs.meal_recommendation import (
            MEAL_RECOMMENDATION_CUISINES,
            MealRecommendationCommands,
        )

        calls = []
        outputs = iter(["메뉴0", "메뉴1", "메뉴0", "메뉴2"] + [f"메뉴{i}" for i in range(3, 22)])

        def fake_custom_prompt_model(**kwargs):
            calls.append(kwargs["prompt"]["variables"])
            return next(outputs)

        cog = MealRecommendationCommands(Mock())
        with patch("cogs.meal_recommendation.custom_prompt_model", fake_custom_prompt_model):
            with patch("cogs.meal_recommendation.asyncio.to_thread", _immediate_to_thread):
                for _ in range(22):
                    asyncio.run(cog.recommend_meal.callback(cog, _FakeInteraction()))

        self.assertEqual(calls[2]["recent_menus"], "메뉴0\n메뉴1")
        self.assertEqual(calls[2]["cuisine"], calls[3]["cuisine"])
        successful_calls = calls[:3] + calls[4:]
        first_cycle = successful_calls[:len(MEAL_RECOMMENDATION_CUISINES)]
        self.assertEqual({call["cuisine"] for call in first_cycle}, set(MEAL_RECOMMENDATION_CUISINES))
        self.assertEqual(list(cog._recent_menus["guild:123"]), [f"메뉴{i}" for i in range(2, 22)])

    def test_previous_menu_state_is_separate_by_guild_and_dm_user(self):
        from cogs.meal_recommendation import MealRecommendationCommands

        calls = []
        outputs = iter(["제육", "제육", "라멘", "라멘"])

        def fake_custom_prompt_model(*args, **kwargs):
            calls.append((args, kwargs))
            return next(outputs)

        cog = MealRecommendationCommands(Mock())
        guild_one = _FakeInteraction(guild_id=10, user_id=1)
        guild_two = _FakeInteraction(guild_id=20, user_id=1)
        dm_user_one = _FakeInteraction(guild_id=None, user_id=1)
        dm_user_two = _FakeInteraction(guild_id=None, user_id=2)

        with patch(
            "cogs.meal_recommendation.custom_prompt_model",
            side_effect=fake_custom_prompt_model,
        ):
            with patch(
                "cogs.meal_recommendation.asyncio.to_thread",
                side_effect=_immediate_to_thread,
            ):
                asyncio.run(cog.recommend_meal.callback(cog, guild_one))
                asyncio.run(cog.recommend_meal.callback(cog, guild_two))
                asyncio.run(cog.recommend_meal.callback(cog, dm_user_one))
                asyncio.run(cog.recommend_meal.callback(cog, dm_user_two))

        guild_one.followup.send.assert_awaited_once_with("# 제육")
        guild_two.followup.send.assert_awaited_once_with("# 제육")
        dm_user_one.followup.send.assert_awaited_once_with("# 라멘")
        dm_user_two.followup.send.assert_awaited_once_with("# 라멘")
        self.assertEqual(len(calls), 4)

    def test_menu_response_uses_first_non_empty_line_only(self):
        from cogs.meal_recommendation import format_meal_recommendation_response

        self.assertEqual(
            format_meal_recommendation_response("\n```md\n# 돈까스\n설명\n```"),
            "# 돈까스",
        )

    def test_menu_response_removes_list_markers_and_trailing_punctuation(self):
        from cogs.meal_recommendation import format_meal_recommendation_response

        self.assertEqual(format_meal_recommendation_response("1. 제육."), "# 제육")
        self.assertEqual(format_meal_recommendation_response("- 돈까스"), "# 돈까스")

    def test_empty_model_output_returns_no_menu(self):
        from cogs.meal_recommendation import format_meal_recommendation_response

        self.assertEqual(format_meal_recommendation_response("   "), "")

    def test_command_uses_safe_error_without_fixed_menu_on_openai_failure(self):
        from cogs.meal_recommendation import MealRecommendationCommands

        cog = MealRecommendationCommands(Mock())
        interaction = _FakeInteraction()

        with patch(
            "cogs.meal_recommendation.custom_prompt_model",
            side_effect=RuntimeError("secret-token"),
        ):
            with patch(
                "cogs.meal_recommendation.asyncio.to_thread",
                side_effect=_immediate_to_thread,
            ):
                with self.assertLogs(
                    "cogs.meal_recommendation", level="ERROR"
                ) as captured:
                    asyncio.run(cog.recommend_meal.callback(cog, interaction))

        sent_message = interaction.followup.send.await_args.args[0]
        self.assertIn("오류", sent_message)
        self.assertNotIn("김치볶음밥", sent_message)
        self.assertIn("secret-token", "\n".join(captured.output))

    def test_command_uses_safe_error_when_retry_still_repeats_previous_menu(self):
        from cogs.meal_recommendation import MealRecommendationCommands

        outputs = iter(["제육", "제육", "제육"])

        def fake_custom_prompt_model(*args, **kwargs):
            return next(outputs)

        cog = MealRecommendationCommands(Mock())
        first_interaction = _FakeInteraction(guild_id=10, user_id=1)
        second_interaction = _FakeInteraction(guild_id=10, user_id=2)

        with patch(
            "cogs.meal_recommendation.custom_prompt_model",
            side_effect=fake_custom_prompt_model,
        ):
            with patch(
                "cogs.meal_recommendation.asyncio.to_thread",
                side_effect=_immediate_to_thread,
            ):
                asyncio.run(cog.recommend_meal.callback(cog, first_interaction))
                with self.assertLogs("cogs.meal_recommendation", level="ERROR"):
                    asyncio.run(cog.recommend_meal.callback(cog, second_interaction))

        first_interaction.followup.send.assert_awaited_once_with("# 제육")
        sent_message = second_interaction.followup.send.await_args.args[0]
        self.assertIn("오류", sent_message)
        self.assertNotIn("김치볶음밥", sent_message)

    def test_meal_recommendation_source_has_no_fixed_menu_fallback(self):
        source = MEAL_RECOMMENDATION_COG_PATH.read_text(encoding="utf-8")

        self.assertNotIn("MEAL_RECOMMENDATION_FALLBACK", source)
        self.assertNotIn("김치볶음밥", source)


if __name__ == "__main__":
    unittest.main()
