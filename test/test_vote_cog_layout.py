import ast
import unittest
from pathlib import Path


VOTE_COG_PATH = Path("cogs/vote/__init__.py")
LEGACY_VOTE_COG_PATH = Path("cogs/vote.py")


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


class VoteCogLayoutTests(unittest.TestCase):
    def test_vote_cog_uses_package_layout(self):
        self.assertTrue(VOTE_COG_PATH.exists())
        self.assertFalse(LEGACY_VOTE_COG_PATH.exists())

    def test_vote_command_and_view_helpers_remain_exposed_from_package_cog(self):
        tree = ast.parse(VOTE_COG_PATH.read_text(encoding="utf-8"))
        class_names = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
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

        self.assertEqual(
            {"VoteCog", "VoteView", "VoteButton"} & class_names,
            {"VoteCog", "VoteView", "VoteButton"},
        )
        self.assertIn("투표", command_names)


if __name__ == "__main__":
    unittest.main()
