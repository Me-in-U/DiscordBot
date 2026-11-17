import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.questions import QuestionCommands


class GodQuestionPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_published_prompt_receives_question_context_and_optional_image(self):
        bot = Mock()
        cog = QuestionCommands(bot)
        for image in (None, SimpleNamespace(url="https://example.com/question.png")):
            with self.subTest(image=image):
                interaction = SimpleNamespace(
                    response=SimpleNamespace(defer=AsyncMock()),
                    followup=SimpleNamespace(send=AsyncMock()),
                    guild=SimpleNamespace(id=123),
                    channel_id=456,
                    user=SimpleNamespace(name="용사"),
                )
                with (
                    patch("cogs.questions.get_recent_messages", return_value="최근 대화") as recent,
                    patch("cogs.questions.custom_prompt_model", return_value="답변") as model,
                ):
                    await cog.to_god.callback(cog, interaction, " 질문 ", image)

                self.assertEqual(model.call_args.kwargs["prompt"], {
                    "id": "pmpt_68acfa93ac6481959537fcb1853c883307d25e6bf62ef36c",
                    "version": "11",
                    "variables": {
                        "recent_messages": "최근 대화",
                        "user_name": "용사",
                        "question": "질문",
                    },
                })
                self.assertEqual(model.call_args.kwargs["image_content"],
                                 [{"role": "user", "content": [{
                                     "type": "input_image", "image_url": image.url,
                                 }]}] if image else None)
                recent.assert_called_once_with(
                    client=bot, guild_id=123, limit=20, channel_id=456,
                    requester=interaction.user,
                )
                interaction.response.defer.assert_awaited_once_with(thinking=True)
                self.assertEqual(interaction.followup.send.await_args.kwargs["content"], "답변")


if __name__ == "__main__":
    unittest.main()
