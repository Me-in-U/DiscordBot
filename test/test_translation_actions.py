import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.translation import (
    TRANSLATION_PROMPT_ID,
    TRANSLATION_PROMPT_VERSION,
    translate_target,
)


class TranslationTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_translate_target_uses_translation_prompt_version_6(self):
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
        self.assertEqual(TRANSLATION_PROMPT_VERSION, "6")
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


if __name__ == "__main__":
    unittest.main()
