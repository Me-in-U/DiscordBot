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


if __name__ == "__main__":
    unittest.main()
