import unittest
from types import SimpleNamespace

from util.maplestory_notice_loop_runner import run_maplestory_notice_loop


class MapleStoryNoticeLoopRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_sent_count_and_logs_non_skipped_failures(self):
        bot = object()
        calls: list[object] = []
        logs: list[str] = []

        async def refresh(bot_arg):
            calls.append(bot_arg)
            return [
                SimpleNamespace(
                    status="ok",
                    action="sent",
                    guild_id=1,
                    channel_id=10,
                    notice_id="100",
                    error=None,
                ),
                SimpleNamespace(
                    status="skipped",
                    action="missing_channel",
                    guild_id=2,
                    channel_id=None,
                    notice_id=None,
                    error=None,
                ),
                SimpleNamespace(
                    status="error",
                    action="send_failed",
                    guild_id=3,
                    channel_id=30,
                    notice_id="300",
                    error="forbidden",
                ),
            ]

        sent_count = await run_maplestory_notice_loop(
            bot,
            refresh_notices=refresh,
            log=logs.append,
        )

        self.assertEqual(calls, [bot])
        self.assertEqual(sent_count, 1)
        self.assertEqual(
            logs,
            [
                "메이플스토리 공지 알림 실패: guild=3 channel=30 notice=300 action=send_failed error=forbidden",
                "메이플스토리 공지 알림 1건 전송 완료",
            ],
        )

    async def test_omits_success_log_when_nothing_was_sent(self):
        logs: list[str] = []

        async def refresh(_bot):
            return [
                SimpleNamespace(
                    status="skipped",
                    action="no_updates",
                    guild_id=1,
                    channel_id=10,
                    notice_id=None,
                    error=None,
                )
            ]

        sent_count = await run_maplestory_notice_loop(
            object(),
            refresh_notices=refresh,
            log=logs.append,
        )

        self.assertEqual(sent_count, 0)
        self.assertEqual(logs, [])


if __name__ == "__main__":
    unittest.main()
