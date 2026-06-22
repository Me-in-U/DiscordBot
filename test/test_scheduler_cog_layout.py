import ast
import unittest
from pathlib import Path


SCHEDULER_COG_PATH = Path("cogs/scheduler/__init__.py")
LEGACY_SCHEDULER_COG_PATH = Path("cogs/scheduler.py")


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


class SchedulerCogLayoutTests(unittest.TestCase):
    def test_scheduler_cog_uses_package_layout(self):
        self.assertTrue(SCHEDULER_COG_PATH.exists())
        self.assertFalse(LEGACY_SCHEDULER_COG_PATH.exists())

    def test_scheduler_group_commands_remain_exposed_from_package_cog(self):
        tree = ast.parse(SCHEDULER_COG_PATH.read_text(encoding="utf-8"))
        group_name = None
        command_names: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if not (
                        isinstance(target, ast.Name)
                        and target.id == "schedule_group"
                        and isinstance(node.value, ast.Call)
                    ):
                        continue
                    for keyword in node.value.keywords:
                        if keyword.arg == "name":
                            group_name = ast.literal_eval(keyword.value)

            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if _decorator_name(decorator) != "schedule_group.command":
                    continue

                command_name = node.name
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == "name":
                            command_name = ast.literal_eval(keyword.value)
                command_names.add(command_name)

        self.assertEqual(group_name, "예약")
        self.assertTrue({"일반", "반복", "리스트"}.issubset(command_names))


if __name__ == "__main__":
    unittest.main()
