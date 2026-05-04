import ast
import unittest
from pathlib import Path


IGNORED_PARAMETERS = {"self", "interaction", "ctx"}


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


def _rename_mapping(decorator: ast.expr) -> dict[str, str]:
    if not isinstance(decorator, ast.Call):
        return {}
    if _decorator_name(decorator.func) != "app_commands.rename":
        return {}

    mapping: dict[str, str] = {}
    for keyword in decorator.keywords:
        if keyword.arg is None:
            continue
        mapping[keyword.arg] = ast.literal_eval(keyword.value)
    return mapping


def _has_ascii_letter(value: str) -> bool:
    return any("a" <= character.lower() <= "z" for character in value)


class SlashOptionNameTests(unittest.TestCase):
    def test_slash_command_option_names_are_localized(self):
        failures: list[str] = []

        for path in sorted(Path("cogs").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                decorator_names = [
                    _decorator_name(decorator) for decorator in node.decorator_list
                ]
                if "app_commands.command" not in decorator_names:
                    continue

                renames: dict[str, str] = {}
                for decorator in node.decorator_list:
                    renames.update(_rename_mapping(decorator))

                for argument in node.args.args:
                    if argument.arg in IGNORED_PARAMETERS:
                        continue

                    display_name = renames.get(argument.arg, argument.arg)
                    if _has_ascii_letter(display_name):
                        failures.append(
                            f"{path}:{node.lineno} {node.name}.{argument.arg}"
                            f" -> {display_name}"
                        )

        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
