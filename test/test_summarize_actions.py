import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.summarize import SummarizeCommands


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
    async def test_conversation_summary_returns_safe_message_on_model_failure(self):
        bot = Mock()
        bot.USER_MESSAGES = {123: ["tester: secret?"]}
        interaction = _FakeInteraction()

        def fake_custom_prompt_model(**kwargs):
            raise RuntimeError("secret-token")

        cog = SummarizeCommands(bot)
        with patch("cogs.summarize.custom_prompt_model", fake_custom_prompt_model):
            with patch("cogs.summarize.get_recent_messages", return_value="대화"):
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
