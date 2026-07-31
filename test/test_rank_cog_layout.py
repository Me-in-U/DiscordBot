import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("OPENAI_KEY", "test-openai-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("RIOT_KEY", "test-riot-key")
os.environ.setdefault("SONPANNO_GUILD_ID", "123")
os.environ.setdefault("SSAFY_GUILD_ID", "456")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_DATABASE", "test")
os.environ.setdefault("DB_USERNAME", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("API_PORT", "1557")
os.environ.setdefault("CELEBRATION_UPDATE_API_KEY", "test")
os.environ.setdefault("ECOS_API_KEY", "test")

from cogs.rank import RankCommands, parse_rank_settings_value


RANK_COG_PATH = Path("cogs/rank/__init__.py")
LEGACY_RANK_COG_PATH = Path("cogs/rank.py")


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


class RankCogLayoutTests(unittest.TestCase):
    def test_rank_cog_uses_package_layout(self):
        self.assertTrue(RANK_COG_PATH.exists())
        self.assertFalse(LEGACY_RANK_COG_PATH.exists())

    def test_rank_commands_remain_exposed_from_package_cog(self):
        tree = ast.parse(RANK_COG_PATH.read_text(encoding="utf-8"))
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

        self.assertTrue(
            {"솔랭", "자랭", "일일랭크", "일일랭크변경", "일일랭크루프"}.issubset(
                command_names
            )
        )

    def test_rank_loop_has_ready_guard_and_unload_cleanup(self):
        source = RANK_COG_PATH.read_text(encoding="utf-8")

        self.assertIn("@update_rank_data.before_loop", source)
        self.assertIn("self.update_rank_data.cancel()", source)

    def test_rank_settings_parser_rejects_corrupt_shape(self):
        with self.assertRaises(ValueError):
            parse_rank_settings_value('["not", "an", "object"]')


class RankRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_corrupt_saved_settings_fall_back_to_defaults(self):
        cog = object.__new__(RankCommands)

        with (
            patch(
                "cogs.rank.fetch_one",
                new=AsyncMock(return_value={"setting_value": "{broken"}),
            ),
            self.assertLogs("cogs.rank", level="WARNING"),
        ):
            settings = await cog._get_full_settings()

        self.assertEqual({}, settings)

    async def test_unexpected_setting_failure_does_not_expose_exception(self):
        cog = object.__new__(RankCommands)
        cog.save_settings = AsyncMock(
            side_effect=RuntimeError("database-password-secret")
        )
        interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=AsyncMock())
        )

        with self.assertLogs("cogs.rank", level="ERROR"):
            await RankCommands.update_daily_rank.callback(
                cog,
                interaction,
                "name#tag",
            )

        message = interaction.response.send_message.await_args.args[0]
        self.assertNotIn("database-password-secret", message)
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )


if __name__ == "__main__":
    unittest.main()
