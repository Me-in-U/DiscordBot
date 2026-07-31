import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from common.discord_ui import SafeView


VIEW_SOURCE_ROOTS = ("cogs", "func", "util")


def _source_files() -> list[Path]:
    paths: list[Path] = []
    for root in VIEW_SOURCE_ROOTS:
        paths.extend(Path(root).rglob("*.py"))
    return sorted(paths)


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_base_name(node.value)}.{node.attr}"
    return ""


class SafeViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_response_hides_exception_details(self):
        response = SimpleNamespace(
            is_done=lambda: False,
            send_message=AsyncMock(),
        )
        interaction = SimpleNamespace(
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
        )

        with self.assertLogs("common.discord_ui", level="ERROR"):
            await SafeView().on_error(
                interaction,
                RuntimeError("secret-token"),
                SimpleNamespace(custom_id="test-button"),
            )

        response.send_message.assert_awaited_once()
        message = response.send_message.await_args.args[0]
        self.assertNotIn("secret-token", message)
        self.assertTrue(response.send_message.await_args.kwargs["ephemeral"])
        interaction.followup.send.assert_not_awaited()

    async def test_deferred_interaction_uses_followup(self):
        response = SimpleNamespace(
            is_done=lambda: True,
            send_message=AsyncMock(),
        )
        interaction = SimpleNamespace(
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
        )

        with self.assertLogs("common.discord_ui", level="ERROR"):
            await SafeView().on_error(
                interaction,
                RuntimeError("secret-token"),
                SimpleNamespace(custom_id="test-button"),
            )

        interaction.followup.send.assert_awaited_once()
        message = interaction.followup.send.await_args.args[0]
        self.assertNotIn("secret-token", message)
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])
        response.send_message.assert_not_awaited()

    def test_feature_views_do_not_inherit_discord_view_directly(self):
        offenders: list[str] = []
        safe_view_count = 0

        for path in _source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                base_names = {_base_name(base) for base in node.bases}
                if "SafeView" in base_names:
                    safe_view_count += 1
                if base_names & {"View", "discord.ui.View"}:
                    offenders.append(f"{path}:{node.lineno}")

        self.assertEqual([], offenders)
        self.assertGreaterEqual(safe_view_count, 20)


if __name__ == "__main__":
    unittest.main()
