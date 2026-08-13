import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.summarize import DISCORD_SUMMARY_PROMPT_VERSION, SummarizeCommands


class _FakeInteraction:
    def __init__(self) -> None:
        self.guild = Mock(id=123)
        self.user = Mock(id=456, name="tester")
        self.response = Mock()
        self.response.send_message = AsyncMock()
        self._message = Mock()
        self._message.edit = AsyncMock()

    async def original_response(self):
        return self._message


class SummarizeActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_summary_passes_recent_images_and_prompt_version(self):
        bot = Mock()
        bot.USER_MESSAGES = {123: {"tester": []}}
        interaction = _FakeInteraction()
        captured_kwargs = {}

        def fake_custom_prompt_model(**kwargs):
            captured_kwargs.update(kwargs)
            return "요약 결과"

        cog = SummarizeCommands(bot)
        with patch("cogs.summarize.custom_prompt_model", fake_custom_prompt_model):
            with patch("cogs.summarize.get_recent_messages", return_value="최근 대화"):
                with patch(
                    "cogs.summarize.get_recent_message_images",
                    return_value=(("최근 이미지", "https://example.com/recent.png"),),
                ):
                    await cog.conversation_summary.callback(
                        cog,
                        interaction,
                        "결정 중심",
                    )

        self.assertEqual(
            captured_kwargs["prompt"]["version"],
            DISCORD_SUMMARY_PROMPT_VERSION,
        )
        self.assertEqual(DISCORD_SUMMARY_PROMPT_VERSION, "7")
        self.assertEqual(
            captured_kwargs["prompt"]["variables"],
            {
                "recent_messages": "최근 대화",
                "additional_requests": "결정 중심",
            },
        )
        self.assertEqual(
            captured_kwargs["image_content"][0]["content"],
            [
                {"type": "input_text", "text": "최근 이미지"},
                {
                    "type": "input_image",
                    "image_url": "https://example.com/recent.png",
                },
            ],
        )

    async def test_conversation_summary_returns_safe_message_on_model_failure(self):
        bot = Mock()
        bot.USER_MESSAGES = {123: ["tester: secret?"]}
        interaction = _FakeInteraction()

        def fake_custom_prompt_model(**kwargs):
            raise RuntimeError("secret-token")

        cog = SummarizeCommands(bot)
        with patch("cogs.summarize.custom_prompt_model", fake_custom_prompt_model):
            with patch("cogs.summarize.get_recent_messages", return_value="대화"):
                with patch(
                    "cogs.summarize.get_recent_message_images",
                    return_value=(),
                ):
                    with self.assertLogs("cogs.summarize", level="ERROR") as captured:
                        await cog.conversation_summary.callback(cog, interaction)

        interaction._message.edit.assert_awaited_once()
        content = interaction._message.edit.await_args.kwargs["content"]
        self.assertIn("대화 요약", content)
        self.assertIn("오류가 발생했습니다", content)
        self.assertNotIn("secret-token", content)
        self.assertNotIn("Error:", content)
        self.assertIn("secret-token", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
