import ast
import unittest
from pathlib import Path


MUSIC_PATH = Path("cogs/music.py")
MUSIC_VIEWS_PATH = Path("util/music_views.py")
MUSIC_STATE_PATH = Path("util/music_state.py")
MUSIC_QUEUE_ACTIONS_PATH = Path("util/music_queue_actions.py")
HELP_PATH = Path("cogs/custom_help.py")
CHANNEL_SETTINGS_PATH = Path("cogs/channel_settings.py")
DB_PATH = Path("util/db.py")


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


def _any_function_node(
    tree: ast.AST,
    function_name: str,
) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function_name:
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
        source_text = MUSIC_VIEWS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SearchResultView":
                source = ast.get_source_segment(source_text, node)
                self.assertIn("timeout=120", source)
                return
        raise AssertionError("SearchResultView class not found")

    def test_search_pick_edits_ephemeral_result_message_for_dismissal(self):
        source_text = MUSIC_VIEWS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SearchResultView":
                source = ast.get_source_segment(source_text, node)
                self.assertIn("interaction.response.edit_message", source)
                self.assertIn("embed=None", source)
                self.assertIn("view=None", source)
                self.assertIn("delete_after=", source)
                self.assertNotIn("_dismiss_search_result_message(interaction)", source)
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
        state_text = MUSIC_STATE_PATH.read_text(encoding="utf-8")

        self.assertIn("IDLE_DISCONNECT_SECONDS = 300", text)
        self.assertIn("idle_disconnect_task: object | None = None", state_text)

    def test_background_task_spawn_logs_task_exceptions(self):
        tree = ast.parse(MUSIC_PATH.read_text(encoding="utf-8"))
        spawn_node = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_spawn_bg"
            ),
            None,
        )
        self.assertIsNotNone(spawn_node, "_spawn_bg function not found")
        source = ast.get_source_segment(MUSIC_PATH.read_text(encoding="utf-8"), spawn_node)

        self.assertIn("task.exception()", source)
        self.assertIn("logger.exception", source)

    def test_queue_added_paths_use_shared_auto_delete_response(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        queue_actions_text = MUSIC_QUEUE_ACTIONS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        self.assertIn(
            'QUEUE_ADDED_MESSAGE = "▶ **대기열에 추가되었습니다.**"',
            queue_actions_text,
        )
        play_source = ast.get_source_segment(source_text, _function_node(tree, "_play"))
        self.assertIn("_send_auto_delete", play_source)
        self.assertIn("url_play_result.user_message", play_source)
        self.assertNotIn("MSG_QUEUE_ADDED", play_source)
        self.assertNotIn('"▶ **대기열에 추가되었습니다.**"', play_source)

        search_pick_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_play_from_search_pick"),
        )
        self.assertIn("_send_auto_delete", search_pick_source)
        self.assertIn("search_pick_result.user_message", search_pick_source)
        self.assertNotIn('"▶ **대기열에 추가되었습니다.**"', search_pick_source)

    def test_play_url_command_delegates_queue_decision_to_action_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        play_source = ast.get_source_segment(source_text, _function_node(tree, "_play"))

        self.assertIn("begin_url_play_action", play_source)
        self.assertIn("url_play_result.should_prepare", play_source)
        self.assertIn("url_play_result.queued_track", play_source)
        self.assertIn("url_play_result.user_message", play_source)
        self.assertNotIn("enqueue_url_track", play_source)
        self.assertNotIn("state.queue", play_source)

    def test_search_pick_command_delegates_queue_decision_to_action_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        function_node = _function_node(tree, "_play_from_search_pick")
        function_source = ast.get_source_segment(source_text, function_node)
        call_names = {
            node.func.id
            for node in ast.walk(function_node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertIn("begin_search_pick_queue_action", function_source)
        self.assertIn("search_pick_result.should_play_now", function_source)
        self.assertIn("search_pick_result.queued_track", function_source)
        self.assertIn("search_pick_result.user_message", function_source)
        self.assertNotIn("enqueue_search_entry_track", call_names)
        self.assertNotIn("normalize_search_entry_url", call_names)

    def test_search_pick_voice_error_uses_shared_auto_delete_response(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        function_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_play_from_search_pick"),
        )

        self.assertIn("await self._send_auto_delete(interaction, error)", function_source)
        self.assertNotIn(
            "msg = await interaction.followup.send(error, ephemeral=True)",
            function_source,
        )

    def test_play_url_voice_error_uses_shared_auto_delete_response(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        function_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_play"),
        )

        self.assertIn("await self._send_auto_delete(", function_source)
        self.assertIn("voice_result.error_message", function_source)
        self.assertNotIn(
            "msg = await interaction.followup.send(\n"
            "                voice_result.error_message",
            function_source,
        )

    def test_play_url_preparation_error_uses_shared_auto_delete_response(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        function_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_play"),
        )

        self.assertIn("MusicPlayerPreparationError", function_source)
        self.assertIn("exc.failure.user_message", function_source)
        self.assertIn("exc.failure.delete_after", function_source)
        self.assertNotIn(
            "msg = await interaction.followup.send(\n"
            "                exc.failure.user_message",
            function_source,
        )

    def test_control_voice_guard_errors_use_shared_auto_delete_response(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        for function_name in (
            "_pause",
            "_resume",
            "_skip",
            "_stop",
            "_seek",
            "_toggle_loop",
        ):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("same_voice_channel_error", function_source)
                self.assertIn("_send_auto_delete(interaction, error)", function_source)
                self.assertNotIn(
                    "msg = await interaction.followup.send(error, ephemeral=True)",
                    function_source,
                )

    def test_control_simple_responses_use_shared_auto_delete_response(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        for function_name in (
            "_pause",
            "_resume",
            "_skip",
            "_stop",
            "_seek",
            "_toggle_loop",
        ):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("_send_auto_delete", function_source)
                self.assertNotIn("self._auto_delete(", function_source)

    def test_favorite_and_queue_display_use_shared_auto_delete_response(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        send_auto_delete_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_send_auto_delete"),
        )
        self.assertIn("embed: Embed | None = None", send_auto_delete_source)
        self.assertIn("embed=embed", send_auto_delete_source)

        for function_name in ("_save_music_favorite", "_show_queue"):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("_send_auto_delete", function_source)
                self.assertNotIn("self._auto_delete(", function_source)

        show_queue_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_show_queue"),
        )
        self.assertIn("embed=embed", show_queue_source)
        self.assertIn("delay=20.0", show_queue_source)

    def test_playback_start_confirmation_uses_shared_auto_delete_response(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        for function_name in ("_play_url_now", "_play"):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("playback_start.confirmation_message", function_source)
                self.assertIn(
                    "self._send_auto_delete(\n"
                    "            interaction,\n"
                    "            playback_start.confirmation_message",
                    function_source,
                )
                self.assertNotIn("msg = await interaction.followup.send", function_source)
                self.assertNotIn("self._auto_delete(", function_source)

    def test_search_result_responses_use_shared_response_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        ephemeral_helper_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_send_ephemeral_response"),
        )
        self.assertIn("discord.NotFound", ephemeral_helper_source)
        self.assertIn("discord.Forbidden", ephemeral_helper_source)
        self.assertIn("discord.HTTPException", ephemeral_helper_source)
        self.assertIn("logger.warning", ephemeral_helper_source)
        self.assertNotIn("except Exception", ephemeral_helper_source)

        response_helper_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_send_music_search_response"),
        )
        self.assertIn("search_result.user_message", response_helper_source)
        self.assertIn("Embed(", response_helper_source)
        self.assertIn("SearchResultView", response_helper_source)
        self.assertIn("favorite_slot=favorite_slot", response_helper_source)
        self.assertIn("_send_ephemeral_response", response_helper_source)

        for function_name in ("_play_music_search_branch", "_search_music_for_favorite_slot"):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("_send_music_search_response", function_source)
                self.assertNotIn("Embed(", function_source)
                self.assertNotIn("SearchResultView", function_source)
                self.assertNotIn("search_result.user_message", function_source)
                self.assertNotIn("search_result.embed_title", function_source)
                self.assertNotIn("search_result.embed_description", function_source)
                self.assertNotIn("interaction.response.send_message", function_source)
                self.assertNotIn("interaction.followup.send", function_source)
                self.assertNotIn("except Exception", function_source)

        play_source = ast.get_source_segment(source_text, _function_node(tree, "_play"))
        self.assertIn("_play_music_search_branch", play_source)
        self.assertNotIn("Embed(", play_source)
        self.assertNotIn("SearchResultView", play_source)
        self.assertNotIn("search_result.user_message", play_source)
        self.assertNotIn("search_result.embed_title", play_source)
        self.assertNotIn("search_result.embed_description", play_source)

    def test_play_and_favorite_search_delegate_result_mapping_to_search_action_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        for function_name in ("_play_music_search_branch", "_search_music_for_favorite_slot"):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("build_music_search_flow", function_source)
                self.assertNotIn("build_music_search_action", function_source)
                self.assertNotIn("run_music_search_query", function_source)
                self.assertIn("_send_music_search_response", function_source)
                self.assertNotIn("run_in_executor", function_source)
                self.assertNotIn("search_ytdl.extract_info", function_source)
                self.assertNotIn("ytsearch10:", function_source)
                self.assertNotIn("search_result.videos", function_source)
                self.assertNotIn("search_result.embed_title", function_source)
                self.assertNotIn("search_result.embed_description", function_source)
                self.assertNotIn("filter_youtube_watch_entries", function_source)
                self.assertNotIn("build_search_results_display", function_source)
                self.assertNotIn("description = \"\\n\".join", function_source)

        play_source = ast.get_source_segment(source_text, _function_node(tree, "_play"))
        self.assertIn("_play_music_search_branch", play_source)
        self.assertNotIn("build_music_search_flow", play_source)
        self.assertNotIn("_send_music_search_response", play_source)

    def test_favorite_search_request_delegates_input_mapping_to_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        function_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_search_music_for_favorite_slot"),
        )

        self.assertIn("build_music_favorite_search_request_action", function_source)
        self.assertIn("favorite_search_action.user_message", function_source)
        self.assertIn("favorite_search_action.query", function_source)
        self.assertIn("favorite_slot=favorite_search_action.slot", function_source)
        self.assertNotIn("validate_music_favorite_slot", function_source)
        self.assertNotIn("(query or \"\").strip()", function_source)
        self.assertNotIn("검색어를 입력", function_source)

    def test_favorite_management_responses_use_shared_ephemeral_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        manager_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_open_music_favorite_manager"),
        )
        self.assertIn("build_music_favorite_manager_open_action", manager_source)
        self.assertIn("_send_ephemeral_response", manager_source)
        self.assertIn("manager_action.status_text", manager_source)
        self.assertIn("manager_action.current_track", manager_source)
        self.assertIn("manager_action.favorites", manager_source)
        self.assertIn("view=view", manager_source)
        self.assertNotIn("_current_player_as_favorite", manager_source)
        self.assertNotIn("view.status_text()", manager_source)
        self.assertNotIn("interaction.followup.send", manager_source)
        self.assertNotIn("interaction.response.send_message", manager_source)

        play_favorite_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_play_music_favorite"),
        )
        self.assertIn("_send_ephemeral_response", play_favorite_source)
        self.assertIn("_play_url_now", play_favorite_source)
        self.assertNotIn("interaction.response.send_message", play_favorite_source)
        self.assertNotIn("interaction.followup.send", play_favorite_source)

    def test_favorite_play_command_delegates_result_mapping_to_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        play_favorite_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_play_music_favorite"),
        )

        self.assertIn("build_music_favorite_play_request_action", play_favorite_source)
        self.assertIn("build_music_favorite_play_action", play_favorite_source)
        self.assertIn("play_request.slot", play_favorite_source)
        self.assertIn("play_result.should_play", play_favorite_source)
        self.assertIn("play_result.user_message", play_favorite_source)
        self.assertIn("play_result.url", play_favorite_source)
        self.assertIn("play_result.success_prefix", play_favorite_source)
        self.assertNotIn("favorite=None).slot", play_favorite_source)
        self.assertNotIn("즐겨찾기가 비어있습니다", play_favorite_source)
        self.assertNotIn("⭐ 즐겨찾기 재생", play_favorite_source)

    def test_favorite_save_commands_delegate_payload_mapping_to_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        save_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_save_music_favorite"),
        )
        self.assertIn("save_music_favorite_payload", save_source)
        self.assertIn("build_music_favorite_save_response_action", save_source)
        self.assertIn("response_action.guild_id", save_source)
        self.assertIn("response_action.user_message", save_source)
        self.assertNotIn("upsert_music_favorite", save_source)
        self.assertNotIn("payload.updated_by", save_source)
        self.assertNotIn("save_result.guild_id", save_source)
        self.assertNotIn("save_result.user_message", save_source)

        search_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_save_search_entry_as_favorite"),
        )
        self.assertIn("build_music_favorite_search_entry_save_action", search_source)
        self.assertIn("save_action.payload", search_source)
        self.assertIn("updated_by=interaction.user.id", search_source)
        self.assertNotIn("search_entry_to_music_favorite_save_payload", search_source)
        self.assertNotIn("normalize_search_entry_url", search_source)
        self.assertNotIn("entry.get", search_source)
        self.assertNotIn("thumbnails", search_source)

        current_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_save_current_track_as_favorite"),
        )
        self.assertIn("current_player_to_music_favorite", current_source)
        self.assertIn("build_music_favorite_current_track_save_action", current_source)
        self.assertIn("current_action.user_message", current_source)
        self.assertIn("current_action.payload", current_source)
        self.assertIn("updated_by=interaction.user.id", current_source)
        self.assertNotIn("_current_player_as_favorite", source_text)
        self.assertNotIn("music_favorite_to_save_payload", current_source)
        self.assertNotIn("if favorite is None", current_source)
        self.assertNotIn("현재 재생 중인 곡 정보", current_source)
        self.assertNotIn("title=favorite.title", current_source)
        self.assertNotIn("thumbnail=favorite.thumbnail", current_source)

    def test_favorite_panel_refresh_delegates_panel_mode_to_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        refresh_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_refresh_music_panel_for_favorites"),
        )

        self.assertIn("build_music_favorite_panel_refresh_action", refresh_source)
        self.assertIn("panel_action.should_refresh", refresh_source)
        self.assertIn("panel_action.should_use_playing_panel", refresh_source)
        self.assertNotIn(
            "state.control_msg is None or state.control_channel is None",
            refresh_source,
        )
        self.assertNotIn("if state.player:", refresh_source)

    def test_panel_and_seek_validation_responses_use_shared_ephemeral_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        panel_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "음악"),
        )
        self.assertIn("_send_ephemeral_response", panel_source)
        self.assertIn("_get_or_create_panel", panel_source)
        self.assertNotIn("interaction.response.send_message", panel_source)
        self.assertNotIn("interaction.followup.send", panel_source)

        seek_command_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "구간이동"),
        )
        self.assertIn("_send_ephemeral_response", seek_command_source)
        self.assertIn("parse_seek_seconds", seek_command_source)
        self.assertIn("시간 형식이 올바르지 않습니다", seek_command_source)
        self.assertNotIn("interaction.response.send_message", seek_command_source)
        self.assertNotIn("interaction.followup.send", seek_command_source)

    def test_music_channel_warning_uses_shared_auto_delete_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        helper_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_send_channel_auto_delete"),
        )
        self.assertIn("await channel.send", helper_source)
        self.assertIn("_spawn_bg", helper_source)
        self.assertIn("_auto_delete(sent_message, delay)", helper_source)
        self.assertIn("discord.NotFound", helper_source)
        self.assertIn("discord.Forbidden", helper_source)
        self.assertIn("discord.HTTPException", helper_source)
        self.assertIn("logger.debug", helper_source)
        self.assertNotIn("except Exception", helper_source)

        on_message_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "on_message"),
        )
        self.assertIn("_send_channel_auto_delete", on_message_source)
        self.assertIn("이 채널은 음악 명령 전용입니다", on_message_source)
        self.assertNotIn("message.channel.send", on_message_source)
        self.assertNotIn("self._auto_delete(", on_message_source)

    def test_cleanup_paths_use_specific_exception_helpers(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        disconnect_helper = ast.get_source_segment(
            source_text,
            _function_node(tree, "_disconnect_voice_client_safely"),
        )
        self.assertIn("discord.ClientException", disconnect_helper)
        self.assertIn("asyncio.TimeoutError", disconnect_helper)
        self.assertIn("OSError", disconnect_helper)
        self.assertIn("logger.debug", disconnect_helper)
        self.assertNotIn("except Exception", disconnect_helper)

        edit_helper = ast.get_source_segment(
            source_text,
            _function_node(tree, "_edit_music_panel_safely"),
        )
        self.assertIn("discord.NotFound", edit_helper)
        self.assertIn("discord.Forbidden", edit_helper)
        self.assertIn("discord.HTTPException", edit_helper)
        self.assertIn("logger.debug", edit_helper)
        self.assertNotIn("except Exception", edit_helper)

        for function_name in ("_idle_disconnect_after_timeout", "_force_stop"):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("_disconnect_voice_client_safely", function_source)
                self.assertIn("_edit_music_panel_safely", function_source)
                self.assertNotIn("disconnect 실패", function_source)
                self.assertNotIn("패널 리셋 실패", function_source)

    def test_storage_loaders_use_specific_db_and_row_exceptions(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        for function_name in ("_load_panel_ids", "_load_music_favorites"):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("aiomysql.Error", function_source)
                self.assertIn("TypeError", function_source)
                self.assertIn("ValueError", function_source)
                self.assertIn("KeyError", function_source)
                self.assertIn("logger.warning", function_source)
                self.assertNotIn("except Exception", function_source)

        favorite_loader = ast.get_source_segment(
            source_text,
            _function_node(tree, "_load_music_favorites"),
        )
        self.assertIn("build_music_favorite_cache_load_action", favorite_loader)
        self.assertIn("cache_action.should_use_cache", favorite_loader)
        self.assertIn("build_music_favorite_cache_hit_result_action", favorite_loader)
        self.assertIn("hit_action.favorites", favorite_loader)
        self.assertNotIn("cache_action.cached_favorites", favorite_loader)
        self.assertIn("build_music_favorite_cache_store_action", favorite_loader)
        self.assertIn("apply_music_favorite_cache_store_action", favorite_loader)
        self.assertIn("build_music_favorite_load_failure_action", favorite_loader)
        self.assertIn("failure_action.guild_id", favorite_loader)
        self.assertIn("failure_action.favorites", favorite_loader)
        self.assertNotIn("guild_id in self._favorite_cache", favorite_loader)
        self.assertNotIn("self._favorite_cache[cache_action.guild_id]", favorite_loader)
        self.assertNotIn("self._favorite_cache[store_action.guild_id]", favorite_loader)
        self.assertNotIn("favorites = []", favorite_loader)

    def test_queue_metadata_loader_uses_runner_helper(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        function_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_fill_queue_meta"),
        )
        self.assertIn("TypeError", function_source)
        self.assertIn("ValueError", function_source)
        self.assertIn("logger.debug", function_source)
        self.assertIn("fill_queue_track_metadata", function_source)
        self.assertNotIn("asyncio.get_event_loop", function_source)
        self.assertNotIn("run_in_executor", function_source)
        self.assertNotIn("extract_queue_track_metadata", function_source)
        self.assertNotIn("apply_queue_track_metadata", function_source)
        self.assertNotIn("info_ytdl.extract_info(track.url", function_source)
        self.assertNotIn("except (DownloadError", function_source)
        self.assertNotIn("except Exception", function_source)
        self.assertNotIn("dbg(", function_source)
        self.assertNotIn("track.title =", function_source)
        self.assertNotIn("thumbnails", function_source)

    def test_playback_control_paths_use_specific_exceptions(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        for function_name in ("_resume", "_seek"):
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("discord.ClientException", function_source)
                self.assertIn("discord.HTTPException", function_source)
                self.assertIn("AttributeError", function_source)
                self.assertIn("TypeError", function_source)
                self.assertIn("ValueError", function_source)
                self.assertIn("logger.warning", function_source)
                self.assertNotIn("except Exception", function_source)
                self.assertNotIn(f"dbg(f\"{function_name}: failed", function_source)

        song_end_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_on_song_end"),
        )
        self.assertIn("except MusicPlayerPreparationError", song_end_source)
        self.assertIn("logger.warning", song_end_source)
        self.assertNotIn("except Exception", song_end_source)
        self.assertNotIn("replay source prepare failed: {type", song_end_source)

    def test_music_remaining_broad_catches_are_lifecycle_logged(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        idle_source = ast.get_source_segment(
            source_text,
            _function_node(tree, "_idle_disconnect_after_timeout"),
        )
        self.assertIn("except Exception", idle_source)
        self.assertIn("logger.exception", idle_source)
        self.assertNotIn("_idle_disconnect_after_timeout: failed", idle_source)

        for function_name in ("_make_default_embed", "_make_playing_embed"):
            function_source = ast.get_source_segment(
                source_text,
                _any_function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn("AttributeError", function_source)
                self.assertIn("TypeError", function_source)
                self.assertIn("ValueError", function_source)
                self.assertIn("logger.exception", function_source)
                self.assertNotIn("except Exception", function_source)

    def test_music_status_output_uses_logger_not_print(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        print_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        self.assertEqual(print_calls, [])

        dbg_source = ast.get_source_segment(
            source_text,
            _any_function_node(tree, "dbg"),
        )
        self.assertIn("logger.debug", dbg_source)
        self.assertNotIn("print(", dbg_source)

    def test_queue_action_commands_delegate_to_action_helpers(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        expected_helpers = {
            "_remove_from_queue": "remove_queue_action",
            "_clear_queue": "clear_queue_action",
            "_move_queue": "move_queue_action",
            "_shuffle_queue": "shuffle_queue_action",
        }
        for function_name, helper_name in expected_helpers.items():
            function_node = _function_node(tree, function_name)
            function_source = ast.get_source_segment(source_text, function_node)
            call_names = {
                node.func.id
                for node in ast.walk(function_node)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            with self.subTest(function_name=function_name):
                self.assertIn(helper_name, function_source)
                self.assertIn("result.user_message", function_source)
                self.assertNotIn("remove_queue_track", call_names)
                self.assertNotIn("move_queue_track", call_names)
                self.assertNotIn("shuffle_queue", call_names)
                self.assertNotIn("state.queue.clear()", function_source)

    def test_playback_commands_delegate_state_changes_to_action_helpers(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        expected_helpers = {
            "_pause": "pause_playback_action",
            "_resume": "resume_playback_action",
            "_stop": "begin_stop_playback_action",
            "_toggle_loop": "toggle_loop_action",
        }
        forbidden_snippets = {
            "_pause": ("state.paused_at = time.time()",),
            "_resume": ("state.start_ts += delta", "state.paused_at = None"),
            "_stop": ("state.is_stopping = True",),
            "_toggle_loop": ("state.is_loop = not state.is_loop",),
        }
        for function_name, helper_name in expected_helpers.items():
            function_source = ast.get_source_segment(
                source_text,
                _function_node(tree, function_name),
            )
            with self.subTest(function_name=function_name):
                self.assertIn(helper_name, function_source)
                self.assertIn("result.user_message", function_source)
                for snippet in forbidden_snippets[function_name]:
                    self.assertNotIn(snippet, function_source)

    def test_skip_and_seek_delegate_state_changes_to_action_helpers(self):
        source_text = MUSIC_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source_text)

        skip_source = ast.get_source_segment(source_text, _function_node(tree, "_skip"))
        self.assertIn("skip_playback_action", skip_source)
        self.assertIn("result.user_message", skip_source)
        self.assertNotIn('"🔁 반복 모드: 처음부터 재생합니다."', skip_source)
        self.assertNotIn('"⏭️ 스킵합니다."', skip_source)
        self.assertNotIn("state.is_skipping = True", skip_source)
        self.assertNotIn("state.is_skipping = False", skip_source)

        seek_source = ast.get_source_segment(source_text, _function_node(tree, "_seek"))
        for helper_name in (
            "validate_seek_playback_action",
            "begin_seek_playback_action",
            "complete_seek_playback_action",
            "fail_seek_playback_action",
        ):
            with self.subTest(helper_name=helper_name):
                self.assertIn(helper_name, seek_source)
        self.assertNotIn("state.is_seeking = True", seek_source)
        self.assertNotIn("state.is_seeking = False", seek_source)
        self.assertNotIn("state.player = player", seek_source)
        self.assertNotIn("state.start_ts = time.time() - seconds", seek_source)
        self.assertNotIn("state.paused_at = None", seek_source)
        self.assertNotIn("초 지점으로 이동했습니다", seek_source)
        self.assertNotIn("곡 길이", seek_source)
        self.assertNotIn("구간 이동 중 오류가 발생했습니다", seek_source)

    def test_music_favorites_are_backed_by_dedicated_table(self):
        db_source = DB_PATH.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS music_favorites", db_source)
        self.assertIn("PRIMARY KEY (guild_id, slot)", db_source)

    def test_music_panel_views_include_favorite_controls(self):
        source = MUSIC_PATH.read_text(encoding="utf-8") + MUSIC_VIEWS_PATH.read_text(encoding="utf-8")

        self.assertIn("MusicFavoriteManageView", source)
        self.assertIn("FavoriteSearchModal", source)
        self.assertIn("music_favorite_manage", source)
        self.assertIn("music_favorite_play_", source)
        self.assertIn("_play_music_favorite", source)
        self.assertIn("_save_current_track_as_favorite", source)

    def test_music_favorite_manager_selection_delegates_to_action_helper(self):
        source_text = MUSIC_VIEWS_PATH.read_text(encoding="utf-8")
        callback_source = source_text[
            source_text.index("class MusicFavoriteSlotSelect"):
            source_text.index("class MusicFavoriteManageView")
        ]
        status_source = source_text[
            source_text.index("class MusicFavoriteManageView"):
            source_text.index("class MusicHelperView")
        ]

        self.assertIn("build_music_favorite_manager_selection_action", callback_source)
        self.assertIn("selection.selected_slot", callback_source)
        self.assertIn("selection.status_text", callback_source)
        self.assertIn("selection.is_default_value", callback_source)
        self.assertNotIn("int(self.values[0])", callback_source)
        self.assertNotIn("option.value == self.values[0]", callback_source)
        self.assertIn("build_music_favorite_manager_selection_action", status_source)

    def test_music_favorite_search_modal_delegates_submit_mapping_to_helper(self):
        source_text = MUSIC_VIEWS_PATH.read_text(encoding="utf-8")
        modal_source = source_text[
            source_text.index("class FavoriteSearchModal"):
            source_text.index("class MusicFavoriteSlotSelect")
        ]
        manager_source = source_text[
            source_text.index("class MusicFavoriteManageView"):
            source_text.index("class MusicHelperView")
        ]

        self.assertIn("build_music_favorite_search_modal_action", modal_source)
        self.assertIn("build_music_favorite_search_submit_action", modal_source)
        self.assertIn("submit_action.slot", modal_source)
        self.assertIn("submit_action.query", modal_source)
        self.assertNotIn("validate_music_favorite_slot", modal_source)
        self.assertNotIn("str(self.query.value or \"\")", modal_source)
        self.assertIn("build_music_favorite_search_modal_action", manager_source)

    def test_music_favorite_current_save_button_delegates_to_action_helper(self):
        source_text = MUSIC_VIEWS_PATH.read_text(encoding="utf-8")
        manager_source = source_text[
            source_text.index("class MusicFavoriteManageView"):
            source_text.index("class MusicHelperView")
        ]

        self.assertIn("build_music_favorite_current_save_button_action", manager_source)
        self.assertIn("current_action.disabled", manager_source)
        self.assertIn("current_action.slot", manager_source)
        self.assertNotIn("disabled=current_track is None", manager_source)
        self.assertNotIn("self.selected_slot,\n        )", manager_source)


if __name__ == "__main__":
    unittest.main()
