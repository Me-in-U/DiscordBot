import ast
import unittest
from pathlib import Path

from common.http import EXTERNAL_HTTP_TIMEOUT


SOURCE_ROOTS = ("api", "bot.py", "cogs", "common", "func", "util")


def _source_files() -> list[Path]:
    paths: list[Path] = []
    for root in SOURCE_ROOTS:
        path = Path(root)
        if path.is_file():
            paths.append(path)
        else:
            paths.extend(path.rglob("*.py"))
    return sorted(paths)


def _is_client_session_call(node: ast.Call) -> bool:
    function = node.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "ClientSession"
    )


class HttpTimeoutPolicyTests(unittest.TestCase):
    def test_shared_timeout_bounds_connect_and_read(self):
        self.assertEqual(30, EXTERNAL_HTTP_TIMEOUT.total)
        self.assertEqual(10, EXTERNAL_HTTP_TIMEOUT.sock_connect)
        self.assertEqual(20, EXTERNAL_HTTP_TIMEOUT.sock_read)

    def test_every_aiohttp_client_session_has_explicit_timeout(self):
        offenders: list[str] = []
        for path in _source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not _is_client_session_call(node):
                    continue
                if not any(keyword.arg == "timeout" for keyword in node.keywords):
                    offenders.append(f"{path}:{node.lineno}")

        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
