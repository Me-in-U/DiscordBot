import ast
import unittest
from pathlib import Path


CELEBRATION_UPDATE_COG_PATH = Path("cogs/celebration_update/__init__.py")
LEGACY_CELEBRATION_UPDATE_COG_PATH = Path("cogs/celebration_update.py")


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


class CelebrationUpdateCogLayoutTests(unittest.TestCase):
    def test_celebration_update_cog_uses_package_layout(self):
        self.assertTrue(CELEBRATION_UPDATE_COG_PATH.exists())
        self.assertFalse(LEGACY_CELEBRATION_UPDATE_COG_PATH.exists())

    def test_celebration_update_command_remains_exposed_from_package_cog(self):
        tree = ast.parse(CELEBRATION_UPDATE_COG_PATH.read_text(encoding="utf-8"))
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

        self.assertIn("기념일업데이트", command_names)


if __name__ == "__main__":
    unittest.main()
