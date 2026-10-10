import os
import unittest
from datetime import datetime, timezone
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("OPENAI_KEY", "test-key")

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

        with patch("cogs.translation.translate_text", AsyncMock(return_value="사용량 한도가 초기화되었습니다.")) as translate:
            message_id = await send_codex_reset_notification(channel, self.event)

        self.assertEqual(message_id, 9876)
        channel.send.assert_awaited_once()
        self.assertEqual(translate.await_args.args, (self.event.text,))
        self.assertEqual(channel.send.await_args.kwargs["embed"].description, "사용량 한도가 초기화되었습니다.")
        self.assertEqual(self.event.text, "Usage limits have been reset.")
        self.assertEqual(
            channel.send.await_args.kwargs["embed"].url,
            self.event.tweet_url,
        )

    async def test_observed_reset_does_not_call_translation(self):
        event = replace(self.event, tweet_url="https://codex-resets.com/")
        channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=1)))
        with patch("cogs.translation.translate_text", AsyncMock()) as translate:
            await send_codex_reset_notification(channel, event)
        translate.assert_not_awaited()
        self.assertEqual(channel.send.await_args.kwargs["embed"].description, event.text)

    async def test_translation_failure_does_not_send_an_error_as_notification(self):
        channel = SimpleNamespace(send=AsyncMock())
        with patch("cogs.translation.translate_text", AsyncMock(side_effect=RuntimeError("translation unavailable"))):
            with self.assertRaises(RuntimeError):
                await send_codex_reset_notification(channel, self.event)
        channel.send.assert_not_awaited()

    async def test_empty_or_non_korean_translation_is_not_sent(self):
        channel = SimpleNamespace(send=AsyncMock())
        for translated in ("", "  ", "Usage limits reset."):
            with self.subTest(translated=translated), patch("cogs.translation.translate_text", AsyncMock(return_value=translated)):
                with self.assertRaises(ValueError):
                    await send_codex_reset_notification(channel, self.event)
        channel.send.assert_not_awaited()

    def test_banked_observation_displays_type_and_tracker_link(self):
        event = replace(self.event, reset_type="banked", tweet_url="https://codex-resets.com/")
        embed = build_codex_reset_embed(event)
        self.assertEqual(embed.url, "https://codex-resets.com/")
        self.assertIn("적립형 리셋", [field.value for field in embed.fields])
        self.assertIn("[출처에서 보기](https://codex-resets.com/)", [field.value for field in embed.fields])


if __name__ == "__main__":
    unittest.main()
