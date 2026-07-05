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
    def __init__(self) -> None:
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

        def fake_generate_text_model(*args, **kwargs):
            calls.append((args, kwargs))
            return "# 제육\n설명"

        cog = MealRecommendationCommands(Mock())
        interaction = _FakeInteraction()

        with patch(
            "cogs.meal_recommendation.generate_text_model",
            side_effect=fake_generate_text_model,
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
        self.assertEqual(kwargs["model"], "gpt-5.4-nano")
        self.assertEqual(kwargs["reasoning_effort"], "none")
        self.assertEqual(kwargs["text_verbosity"], "low")
        self.assertEqual(kwargs["max_output_tokens"], 24)

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

    def test_empty_model_output_falls_back_to_menu_h1(self):
        from cogs.meal_recommendation import format_meal_recommendation_response

        self.assertEqual(format_meal_recommendation_response("   "), "# 김치볶음밥")

    def test_command_uses_menu_h1_fallback_on_openai_failure(self):
        from cogs.meal_recommendation import MealRecommendationCommands

        cog = MealRecommendationCommands(Mock())
        interaction = _FakeInteraction()

        with patch(
            "cogs.meal_recommendation.generate_text_model",
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

        interaction.followup.send.assert_awaited_once_with("# 김치볶음밥")
        self.assertIn("secret-token", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
