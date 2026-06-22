import ast
import unittest
from pathlib import Path


SOURCE_ROOTS = ("api", "bot.py", "cogs", "common", "func", "util")
USER_ACTION_PATHS = (
    Path("cogs/explanation/__init__.py"),
    Path("cogs/interpret.py"),
    Path("cogs/questions/__init__.py"),
    Path("cogs/search/__init__.py"),
    Path("cogs/summarize.py"),
    Path("cogs/translation.py"),
)


def _source_files() -> list[Path]:
    paths: list[Path] = []
    for root in SOURCE_ROOTS:
        path = Path(root)
        if path.is_file():
            paths.append(path)
        else:
            paths.extend(path.rglob("*.py"))
    return sorted(paths)


class ExceptionPolicyTests(unittest.TestCase):
    def test_no_bare_except_in_source(self):
        offenders: list[str] = []
        for path in _source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    offenders.append(f"{path}:{node.lineno}")

        self.assertEqual(offenders, [])

    def test_user_action_paths_do_not_return_raw_error_prefix(self):
        offenders: list[str] = []
        for path in USER_ACTION_PATHS:
            text = path.read_text(encoding="utf-8")
            if "Error:" in text or "오류가 발생했습니다: {e}" in text:
                offenders.append(str(path))

        self.assertEqual(offenders, [])

    def test_traceback_print_exc_is_not_used(self):
        offenders = [
            str(path)
            for path in _source_files()
            if "traceback.print_exc" in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(offenders, [])

    def test_no_silent_broad_exception_pass(self):
        offenders: list[str] = []
        for path in _source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if not isinstance(node.type, ast.Name) or node.type.id != "Exception":
                    continue
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    offenders.append(f"{path}:{node.lineno}")

        self.assertEqual(offenders, [])

    def test_major_loop_task_catches_log_exceptions(self):
        text = Path("cogs/loop/__init__.py").read_text(encoding="utf-8")

        self.assertIn('logger.exception("YouTube 알림 후보 확인 오류")', text)
        self.assertIn('logger.exception("YouTube 커뮤니티 알림 확인 오류")', text)
        self.assertIn('logger.exception("메이플스토리 공지 확인 오류")', text)
        self.assertIn('logger.exception("YouTube WebSub 구독 갱신 오류")', text)


if __name__ == "__main__":
    unittest.main()
