import unittest
from datetime import datetime

from util.weekly_1557_reporter import run_weekly_1557_report


class Weekly1557ReporterTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_report_on_non_monday(self):
        bot = _Bot(channel=_Channel())
        calls: list[str] = []

        sent = await run_weekly_1557_report(
            bot,
            target_channel_id=100,
            now=datetime(2026, 6, 23, 0, 1, 0),
            fetch_counts=lambda: calls.append("fetch") or [],
            clear_counts=lambda: calls.append("clear"),
            log=calls.append,
        )

        self.assertFalse(sent)
        self.assertEqual(calls, [])
        self.assertEqual(bot.channel.messages, [])

    async def test_sends_sorted_report_and_clears_counts_on_monday(self):
        bot = _Bot(channel=_Channel())
        calls: list[str] = []

        async def fetch_counts():
            calls.append("fetch")
            return [
                {"user_id": 2, "count": 3},
                {"user_id": 1, "count": 7},
            ]

        async def clear_counts():
            calls.append("clear")

        sent = await run_weekly_1557_report(
            bot,
            target_channel_id=100,
            now=datetime(2026, 6, 22, 0, 1, 0),
            fetch_counts=fetch_counts,
            clear_counts=clear_counts,
            log=lambda _message: None,
        )

        self.assertTrue(sent)
        self.assertEqual(calls[:2], ["fetch", "clear"])
        self.assertEqual(
            bot.channel.messages,
            ["# 📊 주간 1557 카운트 보고\n<@1>: 7번\n<@2>: 3번"],
        )

    async def test_sends_empty_report_when_no_counts_exist(self):
        bot = _Bot(channel=_Channel())
        calls: list[str] = []

        sent = await run_weekly_1557_report(
            bot,
            target_channel_id=100,
            now=datetime(2026, 6, 22, 0, 1, 0),
            fetch_counts=lambda: [],
            clear_counts=lambda: calls.append("clear"),
            log=lambda _message: None,
        )

        self.assertTrue(sent)
        self.assertEqual(
            bot.channel.messages,
            ["📊 이번 주 1557 카운트 기록된 사용자가 없습니다."],
        )
        self.assertEqual(calls, ["clear"])


class _Channel:
    def __init__(self):
        self.messages: list[str] = []

    async def send(self, message: str) -> None:
        self.messages.append(message)


class _Bot:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id: int):
        if channel_id == 100:
            return self.channel
        return None


if __name__ == "__main__":
    unittest.main()
