import ast
import unittest
from datetime import date
from pathlib import Path


DDAY_COG_PATH = Path("cogs/dday/__init__.py")
LEGACY_DDAY_COG_PATH = Path("cogs/dday.py")
DDAY_UTIL_PATH = Path("util/celebration/dday.py")
LEGACY_DDAY_UTIL_PATH = Path("util/dday.py")
DB_PATH = Path("util/db.py")
LOOP_PATH = Path("cogs/loop/__init__.py")


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


class DdayUtilityTests(unittest.TestCase):
    def test_dday_helper_lives_under_celebration_package(self):
        self.assertTrue(DDAY_UTIL_PATH.exists())
        self.assertFalse(LEGACY_DDAY_UTIL_PATH.exists())

    def test_dday_cog_uses_package_layout(self):
        self.assertTrue(DDAY_COG_PATH.exists())
        self.assertFalse(LEGACY_DDAY_COG_PATH.exists())

    def test_parse_dday_date_accepts_supported_formats(self):
        from util.celebration.dday import parse_dday_date

        self.assertEqual(parse_dday_date("2026-06-04"), date(2026, 6, 4))
        self.assertEqual(parse_dday_date("2026.06.04"), date(2026, 6, 4))
        self.assertEqual(parse_dday_date("2026/06/04"), date(2026, 6, 4))
        self.assertEqual(parse_dday_date("20260604"), date(2026, 6, 4))

    def test_parse_dday_date_rejects_invalid_dates(self):
        from util.celebration.dday import parse_dday_date

        for value in ("2026-02-30", "26-06-04", "2026년6월4일", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_dday_date(value)

    def test_calculate_dday_label_formats_today_future_and_past(self):
        from util.celebration.dday import calculate_dday_label

        today = date(2026, 6, 4)

        self.assertEqual(calculate_dday_label(today, today), "D-Day")
        self.assertEqual(calculate_dday_label(date(2026, 6, 10), today), "D-6")
        self.assertEqual(calculate_dday_label(date(2026, 6, 1), today), "D+3")

    def test_filter_visible_dday_events_excludes_past_items_by_default(self):
        from util.celebration.dday import DdayEvent, filter_visible_dday_events

        today = date(2026, 6, 4)
        events = [
            DdayEvent(1, 10, "지난 기본값", date(2026, 6, 1), False, 100),
            DdayEvent(2, 10, "지난 유지", date(2026, 6, 1), True, 100),
            DdayEvent(3, 10, "오늘", today, False, 100),
            DdayEvent(4, 10, "미래", date(2026, 6, 10), False, 100),
        ]

        visible_titles = [
            event.title for event in filter_visible_dday_events(events, today)
        ]

        self.assertEqual(visible_titles, ["오늘", "미래", "지난 유지"])

    def test_build_dday_list_embed_groups_events(self):
        from util.celebration.dday import DdayEvent, build_dday_list_embed

        today = date(2026, 6, 4)
        events = [
            DdayEvent(1, 10, "지난 기본값", date(2026, 6, 1), False, 100),
            DdayEvent(2, 10, "지난 유지", date(2026, 6, 1), True, 100),
            DdayEvent(3, 10, "오늘", today, False, 100),
            DdayEvent(4, 10, "미래", date(2026, 6, 10), False, 100),
        ]

        embed = build_dday_list_embed(events, today=today)

        self.assertEqual(embed.title, "📅 DDAY 목록")
        self.assertEqual(
            [field.name for field in embed.fields],
            ["오늘 D-0", "다가오는 D-DAY", "지난 D+DAY", "자동 공지 제외"],
        )


class DdaySchemaAndCommandTests(unittest.TestCase):
    def test_schema_defines_dday_events_table(self):
        db_source = DB_PATH.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS dday_events", db_source)
        for column_name in (
            "id",
            "guild_id",
            "title",
            "target_date",
            "show_after",
            "created_by",
            "created_at",
            "updated_at",
        ):
            self.assertIn(column_name, db_source)

    def test_dday_commands_exist_with_localized_options(self):
        tree = ast.parse(
            DDAY_COG_PATH.read_text(encoding="utf-8"),
            filename=str(DDAY_COG_PATH),
        )
        command_names: set[str] = set()
        add_node = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if _decorator_name(decorator) != "app_commands.command":
                    continue
                command_name = None
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == "name":
                            command_name = ast.literal_eval(keyword.value)
                command_names.add(command_name or node.name)
                if command_name == "dday추가":
                    add_node = node

        self.assertEqual({"dday추가", "dday삭제", "dday목록"} & command_names, {"dday추가", "dday삭제", "dday목록"})
        self.assertIsNotNone(add_node)

        renames: dict[str, str] = {}
        for decorator in add_node.decorator_list:
            renames.update(_rename_mapping(decorator))

        self.assertEqual(renames["date_text"], "날짜")
        self.assertEqual(renames["title"], "제목")
        self.assertEqual(renames["show_after"], "지난날짜표시")

    def test_daily_refresh_runner_refreshes_dday_and_sunday_maple_after_celebration(self):
        runner_path = Path("util/loop/daily_refresh_runner.py")
        runner_source = runner_path.read_text(encoding="utf-8")
        tree = ast.parse(runner_source, filename=str(runner_path))
        run_daily_refreshes = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_daily_refreshes"
        )
        source = ast.get_source_segment(runner_source, run_daily_refreshes)
        self.assertIsNotNone(source)

        celebration_index = source.index("refresh_celebration")
        dday_index = source.index("refresh_dday")
        sunday_maple_index = source.index("refresh_sunday_maple")
        reload_index = source.index("bot.USER_MESSAGES")

        self.assertLess(celebration_index, dday_index)
        self.assertLess(dday_index, sunday_maple_index)
        self.assertLess(sunday_maple_index, reload_index)
        self.assertIn("weekday() == 6", source)

    def test_help_mentions_dday_commands(self):
        help_source = Path("cogs/custom_help.py").read_text(encoding="utf-8")

        self.assertIn("`/dday추가", help_source)
        self.assertIn("`/dday삭제`", help_source)
        self.assertIn("`/dday목록`", help_source)


class DdayDeleteViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_view_paginates_more_than_twenty_five_events(self):
        from cogs.dday import DdayDeleteView
        from util.celebration.dday import DdayEvent

        events = [
            DdayEvent(index, 10, f"이벤트 {index}", date(2026, 6, index), False, 100)
            for index in range(1, 27)
        ]

        view = DdayDeleteView(requester_id=100, guild_id=10, events=events)
        labels = [getattr(child, "label", None) for child in view.children]

        self.assertIn("이전", labels)
        self.assertIn("다음", labels)

    async def test_delete_view_rejects_other_users(self):
        from cogs.dday import DdayDeleteView
        from util.celebration.dday import DdayEvent

        view = DdayDeleteView(
            requester_id=100,
            guild_id=10,
            events=[DdayEvent(1, 10, "테스트", date(2026, 6, 4), False, 100)],
        )
        interaction = _Interaction(user_id=200)

        allowed = await view._check_requester(interaction)

        self.assertFalse(allowed)
        self.assertEqual(
            interaction.response.sent_message,
            "이 삭제 메뉴는 명령어를 실행한 사용자만 조작할 수 있습니다.",
        )
        self.assertTrue(interaction.response.sent_kwargs["ephemeral"])


class _User:
    def __init__(self, user_id: int):
        self.id = user_id


class _Response:
    def __init__(self):
        self.sent_message = None
        self.sent_kwargs = None

    async def send_message(self, message, **kwargs):
        self.sent_message = message
        self.sent_kwargs = kwargs


class _Interaction:
    def __init__(self, user_id: int):
        self.user = _User(user_id)
        self.response = _Response()


if __name__ == "__main__":
    unittest.main()
