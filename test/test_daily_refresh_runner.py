import unittest
import warnings
from datetime import datetime
from types import SimpleNamespace

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="'audioop' is deprecated and slated for removal in Python 3.13",
        category=DeprecationWarning,
    )
    from util.daily_refresh_runner import run_daily_refreshes


class DailyRefreshRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_daily_refreshes_in_order_and_resets_message_cache(self):
        calls: list[str] = []
        bot = SimpleNamespace(USER_MESSAGES={"guild": ["message"]})

        async def refresh_celebration(bot_arg):
            self.assertIs(bot_arg, bot)
            calls.append("celebration")
            return [SimpleNamespace(status="ok", guild_id=1, channel_id=10, error=None)]

        async def refresh_dday(bot_arg):
            self.assertIs(bot_arg, bot)
            calls.append("dday")
            return [SimpleNamespace(status="ok", guild_id=1, channel_id=20, error=None)]

        async def refresh_sunday_maple(bot_arg):
            self.assertIs(bot_arg, bot)
            calls.append("sunday_maple")
            return [SimpleNamespace(status="ok", guild_id=1, channel_id=30, error=None)]

        async def reload_recent_messages():
            calls.append("reload")

        summary = await run_daily_refreshes(
            bot,
            now=datetime(2026, 6, 28, 0, 0, 0),
            reload_recent_messages=reload_recent_messages,
            refresh_celebration=refresh_celebration,
            refresh_dday=refresh_dday,
            refresh_sunday_maple=refresh_sunday_maple,
            log=lambda message: calls.append(f"log:{message}"),
        )

        refresh_calls = [call for call in calls if not call.startswith("log:")]
        self.assertEqual(refresh_calls, ["celebration", "dday", "sunday_maple", "reload"])
        self.assertEqual(bot.USER_MESSAGES, {})
        self.assertEqual(summary.celebration_success_count, 1)
        self.assertEqual(summary.dday_success_count, 1)
        self.assertEqual(summary.sunday_maple_success_count, 1)

    async def test_skips_sunday_maple_on_non_sunday(self):
        calls: list[str] = []
        bot = SimpleNamespace(USER_MESSAGES={})

        async def refresh_empty(bot_arg):
            calls.append("refresh")
            return []

        async def refresh_sunday_maple(bot_arg):
            raise AssertionError("sunday maple refresh should not run on non-Sunday")

        async def reload_recent_messages():
            calls.append("reload")

        summary = await run_daily_refreshes(
            bot,
            now=datetime(2026, 6, 23, 0, 0, 0),
            reload_recent_messages=reload_recent_messages,
            refresh_celebration=refresh_empty,
            refresh_dday=refresh_empty,
            refresh_sunday_maple=refresh_sunday_maple,
            log=lambda message: None,
        )

        self.assertEqual(calls, ["refresh", "refresh", "reload"])
        self.assertEqual(summary.sunday_maple_success_count, 0)
