import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from util.codex_resets.fetcher import CodexResetEvent
from util.codex_resets.sender import (
    build_codex_reset_embed,
    send_codex_reset_notification,
)


class CodexResetsSenderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.event = CodexResetEvent(
            tweet_id="200",
            tweet_url="https://x.com/example/status/200",
            text="Usage limits have been reset.",
            announced_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        )

    def test_builds_unofficial_tracker_embed(self):
        embed = build_codex_reset_embed(self.event)

        self.assertEqual(embed.title, "Codex 사용량 리셋 감지")
        self.assertEqual(embed.url, self.event.tweet_url)
        self.assertEqual(embed.description, self.event.text)
        self.assertEqual(embed.timestamp, self.event.announced_at)
        self.assertIn("codex-resets.com", embed.footer.text)
        self.assertIn("비공식", embed.footer.text)

    async def test_sends_reset_embed_and_returns_message_id(self):
        channel = SimpleNamespace(
            send=AsyncMock(return_value=SimpleNamespace(id=9876))
        )

        message_id = await send_codex_reset_notification(channel, self.event)

        self.assertEqual(message_id, 9876)
        channel.send.assert_awaited_once()
        self.assertEqual(
            channel.send.await_args.kwargs["embed"].url,
            self.event.tweet_url,
        )


if __name__ == "__main__":
    unittest.main()
