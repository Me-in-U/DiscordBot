from datetime import datetime
import unittest

from bot import SEOUL_TZ
from cogs.scheduler import calculate_recurring_trigger_time


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


if __name__ == "__main__":
    unittest.main()
