import ast
import unittest
from pathlib import Path


INTERPRET_COG_PATH = Path("cogs/interpret/__init__.py")
LEGACY_INTERPRET_COG_PATH = Path("cogs/interpret.py")


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


class InterpretCogLayoutTests(unittest.TestCase):
    def test_interpret_cog_uses_package_layout(self):
        self.assertTrue(INTERPRET_COG_PATH.exists())
        self.assertFalse(LEGACY_INTERPRET_COG_PATH.exists())

    def test_interpret_command_remains_exposed_from_package_cog(self):
        tree = ast.parse(INTERPRET_COG_PATH.read_text(encoding="utf-8"))
        command_names: set[str] = set()
        context_menu_names: set[str] = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                decorator_name = _decorator_name(decorator)
                if decorator_name not in {
                    "app_commands.command",
                    "app_commands.context_menu",
                }:
                    continue

                command_name = node.name
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == "name":
                            command_name = ast.literal_eval(keyword.value)

                if decorator_name == "app_commands.context_menu":
                    context_menu_names.add(command_name)
                else:
                    command_names.add(command_name)

        self.assertIn("해석", command_names)
        self.assertIn("메시지 해석", context_menu_names)


if __name__ == "__main__":
    unittest.main()
