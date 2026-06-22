import ast
import unittest
from pathlib import Path


EMOJI_ENLARGE_COG_PATH = Path("cogs/emoji_enlarge/__init__.py")
LEGACY_EMOJI_ENLARGE_COG_PATH = Path("cogs/emoji_enlarge.py")


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


class EmojiEnlargeCogLayoutTests(unittest.TestCase):
    def test_emoji_enlarge_cog_uses_package_layout(self):
        self.assertTrue(EMOJI_ENLARGE_COG_PATH.exists())
        self.assertFalse(LEGACY_EMOJI_ENLARGE_COG_PATH.exists())

    def test_on_message_listener_remains_exposed_from_package_cog(self):
        tree = ast.parse(EMOJI_ENLARGE_COG_PATH.read_text(encoding="utf-8"))
        listener_names: set[str] = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if any(
                _decorator_name(decorator) == "commands.Cog.listener"
                for decorator in node.decorator_list
            ):
                listener_names.add(node.name)

        self.assertIn("on_message", listener_names)


if __name__ == "__main__":
    unittest.main()
