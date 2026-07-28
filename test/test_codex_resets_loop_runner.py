import unittest
from types import SimpleNamespace

from util.codex_resets.loop_runner import run_codex_reset_notification_loop


class CodexResetsLoopRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_sent_notifications_and_logs_failures(self):
        logs = []

        async def refresh(_bot):
            return [
                SimpleNamespace(
                    guild_id=1,
                    channel_id=10,
                    tweet_id="100",
                    message_id=1000,
                    status="ok",
                    action="sent",
                    error=None,
                ),
                SimpleNamespace(
                    guild_id=2,
                    channel_id=20,
                    tweet_id="200",
                    message_id=None,
                    status="error",
                    action="send_failed",
                    error="forbidden",
                ),
                SimpleNamespace(
                    guild_id=3,
                    channel_id=30,
                    tweet_id=None,
                    message_id=None,
                    status="skipped",
                    action="seeded",
                    error=None,
                ),
            ]

        sent_count = await run_codex_reset_notification_loop(
            object(),
            refresh_notifications=refresh,
            log=logs.append,
        )

        self.assertEqual(sent_count, 1)
        self.assertEqual(
            logs,
            [
                "Codex 리셋 알림 실패: guild=2 channel=20 tweet=200 "
                "action=send_failed error=forbidden",
                "Codex 리셋 알림 1건 전송 완료",
            ],
        )


if __name__ == "__main__":
    unittest.main()
