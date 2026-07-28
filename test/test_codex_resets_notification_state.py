import unittest
from unittest.mock import AsyncMock, patch

from util.codex_resets.notification_state import (
    CodexResetNotificationState,
    load_codex_reset_notification_state,
    save_codex_reset_notification_state,
)


class CodexResetsNotificationStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_guild_state_from_setting_data(self):
        with patch(
            "util.codex_resets.notification_state.fetch_one",
            new=AsyncMock(
                return_value={
                    "setting_value": (
                        '{"lastTweetId":"200",'
                        '"lastAnnouncedAt":"2026-07-21T00:00:00+00:00"}'
                    )
                }
            ),
        ):
            state = await load_codex_reset_notification_state(10)

        self.assertEqual(
            state,
            CodexResetNotificationState(
                last_tweet_id="200",
                last_announced_at="2026-07-21T00:00:00+00:00",
            ),
        )

    async def test_saves_guild_state_with_upsert(self):
        execute_query = AsyncMock()
        state = CodexResetNotificationState(
            last_tweet_id="300",
            last_announced_at="2026-07-22T00:00:00+00:00",
        )

        with patch(
            "util.codex_resets.notification_state.execute_query",
            new=execute_query,
        ):
            await save_codex_reset_notification_state(10, state)

        query, params = execute_query.await_args.args
        self.assertIn("ON DUPLICATE KEY UPDATE", query)
        self.assertEqual(params[0], "codexResetNotification:10")
        self.assertIn('"lastTweetId": "300"', params[1])


if __name__ == "__main__":
    unittest.main()
