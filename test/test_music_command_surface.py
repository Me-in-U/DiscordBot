import ast
import unittest
from pathlib import Path


MUSIC_PATH = Path("cogs/music.py")
HELP_PATH = Path("cogs/custom_help.py")
CHANNEL_SETTINGS_PATH = Path("cogs/channel_settings.py")


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


def _music_command_names() -> set[str]:
    tree = ast.parse(MUSIC_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if _decorator_name(decorator) != "app_commands.command":
                continue
            if not isinstance(decorator, ast.Call):
                names.add(node.name)
                continue
            command_name = None
            for keyword in decorator.keywords:
                if keyword.arg == "name":
                    command_name = ast.literal_eval(keyword.value)
            names.add(command_name or node.name)
    return names


def _function_node(tree: ast.AST, function_name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"{function_name} function not found")


class MusicCommandSurfaceTests(unittest.TestCase):
    def test_music_cog_exposes_button_actions_as_slash_commands(self):
        self.assertTrue(
            {
                "음악",
                "재생",
                "일시정지",
                "다시재생",
                "정지",
                "스킵",
                "대기열",
                "구간이동",
                "반복",
                "대기열삭제",
                "대기열비우기",
                "대기열이동",
                "셔플",
            }.issubset(_music_command_names())
        )

    def test_music_help_matches_existing_commands(self):
        help_text = HELP_PATH.read_text(encoding="utf-8")

        self.assertNotIn("`/들어와`", help_text)
        self.assertNotIn("`/볼륨 [0~200]`", help_text)
        for command_name in (
            "스킵",
            "대기열",
            "구간이동",
            "반복",
            "대기열삭제",
            "대기열비우기",
            "대기열이동",
            "셔플",
        ):
            self.assertIn(f"`/{command_name}", help_text)

    def test_channel_settings_can_configure_music_channel(self):
        text = CHANNEL_SETTINGS_PATH.read_text(encoding="utf-8")

        self.assertIn('"music": "음악"', text)
        self.assertIn('app_commands.Choice(name="음악", value="music")', text)

    def test_seek_restarts_playback_with_guild_id(self):
        tree = ast.parse(MUSIC_PATH.read_text(encoding="utf-8"))
        seek_node = _function_node(tree, "_seek")
        vc_play_calls = [
            node
            for node in ast.walk(seek_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_vc_play"
        ]

        self.assertTrue(vc_play_calls)
        self.assertTrue(
            any(
                any(keyword.arg == "guild_id" for keyword in call.keywords)
                for call in vc_play_calls
            )
        )

    def test_updater_does_not_advance_queue_directly(self):
        tree = ast.parse(MUSIC_PATH.read_text(encoding="utf-8"))
        updater_node = _function_node(tree, "_updater_loop")

        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_on_song_end"
                for node in ast.walk(updater_node)
            )
        )

    def test_search_results_have_finite_timeout(self):
        tree = ast.parse(MUSIC_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SearchResultView":
                source = ast.get_source_segment(MUSIC_PATH.read_text(encoding="utf-8"), node)
                self.assertIn("timeout=120", source)
                return
        raise AssertionError("SearchResultView class not found")

    def test_search_pick_dismisses_result_message(self):
        tree = ast.parse(MUSIC_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SearchResultView":
                source = ast.get_source_segment(MUSIC_PATH.read_text(encoding="utf-8"), node)
                self.assertIn("_dismiss_search_result_message(interaction)", source)
                return
        raise AssertionError("SearchResultView class not found")

    def test_empty_queue_schedules_idle_disconnect_instead_of_immediate_stop(self):
        tree = ast.parse(MUSIC_PATH.read_text(encoding="utf-8"))
        on_song_end = _function_node(tree, "_on_song_end")
        source = ast.get_source_segment(
            MUSIC_PATH.read_text(encoding="utf-8"), on_song_end
        )

        self.assertIn("_schedule_idle_disconnect(guild_id)", source)
        self.assertIn("no next track -> reset panel and wait for idle timeout", source)
        self.assertNotIn("no next track -> stop and reset panel", source)

    def test_idle_disconnect_state_is_explicit(self):
        text = MUSIC_PATH.read_text(encoding="utf-8")

        self.assertIn("IDLE_DISCONNECT_SECONDS = 300", text)
        self.assertIn("idle_disconnect_task: Optional[asyncio.Task] = None", text)


if __name__ == "__main__":
    unittest.main()
