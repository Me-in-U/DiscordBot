from datetime import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot import SEOUL_TZ
from cogs.scheduler import SchedulerCog, calculate_recurring_trigger_time


class SchedulerRecurringTests(unittest.TestCase):
    def test_hourly_recurring_trigger_uses_positive_hour_interval(self):
        now = datetime(2026, 6, 23, 10, 30, tzinfo=SEOUL_TZ)

        trigger_time = calculate_recurring_trigger_time(now, "hourly", "3")

        self.assertEqual(trigger_time, datetime(2026, 6, 23, 13, 30, tzinfo=SEOUL_TZ))

    def test_daily_recurring_trigger_rolls_to_tomorrow_when_time_has_passed(self):
        now = datetime(2026, 6, 23, 10, 30, tzinfo=SEOUL_TZ)

        trigger_time = calculate_recurring_trigger_time(now, "daily", "09:15")

        self.assertEqual(trigger_time, datetime(2026, 6, 24, 9, 15, tzinfo=SEOUL_TZ))

    def test_recurring_trigger_rejects_invalid_hourly_value(self):
        now = datetime(2026, 6, 23, 10, 30, tzinfo=SEOUL_TZ)

        with self.assertRaisesRegex(ValueError, "hourly"):
            calculate_recurring_trigger_time(now, "hourly", "abc")

    def test_recurring_trigger_rejects_non_positive_hourly_value(self):
        now = datetime(2026, 6, 23, 10, 30, tzinfo=SEOUL_TZ)

        with self.assertRaisesRegex(ValueError, "hourly"):
            calculate_recurring_trigger_time(now, "hourly", "0")


class SchedulerDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def build_cog(self, channel):
        cog = object.__new__(SchedulerCog)
        cog.bot = SimpleNamespace(get_channel=lambda _channel_id: channel)
        return cog

    def build_row(self):
        return {
            "id": "schedule-1",
            "channel_id": 123,
            "user_id": 456,
            "message": "hello",
            "is_recurring": False,
            "trigger_time": datetime(2026, 7, 31, tzinfo=SEOUL_TZ),
        }

    async def test_failed_send_keeps_schedule_for_retry(self):
        channel = SimpleNamespace(
            send=AsyncMock(side_effect=RuntimeError("send failed"))
        )
        cog = self.build_cog(channel)

        with (
            patch(
                "cogs.scheduler.fetch_all",
                new=AsyncMock(return_value=[self.build_row()]),
            ),
            patch("cogs.scheduler.execute_query", new=AsyncMock()) as execute_query,
            self.assertLogs("cogs.scheduler", level="ERROR"),
        ):
            await cog._run_schedule_check()

        execute_query.assert_not_awaited()

    async def test_missing_channel_keeps_schedule_for_retry(self):
        cog = self.build_cog(None)

        with (
            patch(
                "cogs.scheduler.fetch_all",
                new=AsyncMock(return_value=[self.build_row()]),
            ),
            patch("cogs.scheduler.execute_query", new=AsyncMock()) as execute_query,
            self.assertLogs("cogs.scheduler", level="WARNING"),
        ):
            await cog._run_schedule_check()

        execute_query.assert_not_awaited()

    async def test_successful_one_time_send_deletes_schedule(self):
        channel = SimpleNamespace(send=AsyncMock())
        cog = self.build_cog(channel)

        with (
            patch(
                "cogs.scheduler.fetch_all",
                new=AsyncMock(return_value=[self.build_row()]),
            ),
            patch("cogs.scheduler.execute_query", new=AsyncMock()) as execute_query,
        ):
            await cog._run_schedule_check()

        channel.send.assert_awaited_once()
        execute_query.assert_awaited_once_with(
            "DELETE FROM scheduled_messages WHERE id = %s",
            ("schedule-1",),
        )

    async def test_query_failure_does_not_terminate_iteration_method(self):
        cog = self.build_cog(None)

        with (
            patch(
                "cogs.scheduler.fetch_all",
                new=AsyncMock(side_effect=RuntimeError("database unavailable")),
            ),
            self.assertLogs("cogs.scheduler", level="ERROR"),
        ):
            await cog._run_schedule_check()


if __name__ == "__main__":
    unittest.main()
