import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.translation import (
    TRANSLATION_PROMPT_ID,
    TRANSLATION_PROMPT_VERSION,
    translate_target,
    translate_text,
)


class TranslationTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_translate_target_uses_current_translation_prompt(self):
        captured_kwargs = {}

        def fake_custom_prompt_model(**kwargs):
            captured_kwargs.update(kwargs)
            return "번역 결과"

        with patch("cogs.translation.custom_prompt_model", fake_custom_prompt_model):
            result = await translate_target(" example target_message ", None)

        self.assertEqual(result, "번역 결과")
        self.assertEqual(
            captured_kwargs["prompt"],
            {
                "id": TRANSLATION_PROMPT_ID,
                "version": TRANSLATION_PROMPT_VERSION,
                "variables": {"target_message": "example target_message"},
            },
        )
        self.assertEqual(TRANSLATION_PROMPT_VERSION, "10")
        self.assertIsNone(captured_kwargs["image_content"])

    async def test_translate_target_returns_safe_message_on_model_failure(self):
        def fake_custom_prompt_model(**kwargs):
            raise RuntimeError("secret-token")

        with patch("cogs.translation.custom_prompt_model", fake_custom_prompt_model):
            with self.assertLogs("cogs.translation", level="ERROR") as captured:
                result = await translate_target(" example target_message ", None)

        self.assertIn("번역", result)
        self.assertIn("오류가 발생했습니다", result)
        self.assertNotIn("secret-token", result)
        self.assertNotIn("Error:", result)
        self.assertIn("secret-token", "\n".join(captured.output))

    async def test_shared_translation_accepts_summary_instructions_and_raises_errors(self):
        with patch("cogs.translation.custom_prompt_model", return_value="요약") as model:
            self.assertEqual(await translate_text("source", instructions="한국어로 요약"), "요약")
        self.assertEqual(model.call_args.kwargs["instructions"], "한국어로 요약")
        self.assertEqual(model.call_args.kwargs["prompt"]["id"], TRANSLATION_PROMPT_ID)
        self.assertEqual(
            model.call_args.kwargs["image_content"],
            [{"role": "user", "content": [{"type": "input_text", "text": "source"}]}],
        )
        with patch("cogs.translation.custom_prompt_model", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                await translate_text("source")

    async def test_custom_translation_sends_source_as_api_input_and_preserves_image(self):
        from api.chatGPT import custom_prompt_model

        with patch("cogs.translation.custom_prompt_model", custom_prompt_model):
            with patch("api.chatGPT.clientGPT.responses.create") as create:
                create.return_value.output_text = "리셋이 모든 계정에 반영됐습니다."
                await translate_text(
                    " All propagated. ",
                    "https://example.com/image.png",
                    instructions="한국어 번역문만 반환하세요.",
                )

        self.assertEqual(
            create.call_args.kwargs["input"],
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "All propagated."},
                        {"type": "input_image", "image_url": "https://example.com/image.png"},
                    ],
                }
            ],
        )
        self.assertEqual(create.call_args.kwargs["instructions"], "한국어 번역문만 반환하세요.")

    def test_custom_prompt_forwards_optional_instructions(self):
        from api.chatGPT import custom_prompt_model

        with patch("api.chatGPT.clientGPT.responses.create") as create:
            create.return_value.output_text = "요약"
            self.assertEqual(custom_prompt_model({"id": "example"}, instructions="한국어 요약"), "요약")
            create.assert_called_once_with(prompt={"id": "example"}, instructions="한국어 요약")
            create.reset_mock()
            custom_prompt_model({"id": "example"})
            create.assert_called_once_with(prompt={"id": "example"})


if __name__ == "__main__":
    unittest.main()
