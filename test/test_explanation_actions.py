import os
import unittest

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.explanation import (
    EXPLANATION_PROMPT_ID,
    EXPLANATION_PROMPT_VERSION,
    build_explanation_option_label,
    build_explanation_prompt,
)
from common.openai_prompt import build_single_image_content


class ExplanationActionTests(unittest.TestCase):
    def test_image_only_option_label_is_image_marker(self):
        self.assertEqual(build_explanation_option_label("", True), "(이미지)")

    def test_text_option_label_uses_message_text(self):
        self.assertEqual(
            build_explanation_option_label("  설명할 텍스트  ", True),
            "설명할 텍스트",
        )

    def test_long_option_label_is_truncated(self):
        label = build_explanation_option_label("가" * 55, False)

        self.assertEqual(label, "가" * 50 + "...")

    def test_build_explanation_prompt_uses_prompt_id_and_version(self):
        prompt = build_explanation_prompt(" 설명할 내용 ")

        self.assertEqual(
            prompt,
            {
                "id": EXPLANATION_PROMPT_ID,
                "version": EXPLANATION_PROMPT_VERSION,
                "variables": {"target_message": "설명할 내용"},
            },
        )

    def test_build_explanation_prompt_uses_image_fallback_text(self):
        prompt = build_explanation_prompt("   ", has_image=True)

        self.assertEqual(
            prompt["variables"]["target_message"],
            "첨부 이미지의 내용을 설명해줘.",
        )

    def test_common_image_content_includes_image(self):
        payload = build_single_image_content("https://cdn.example/image.png")

        content = payload[0]["content"]
        self.assertEqual(
            content[0],
            {
                "type": "input_image",
                "image_url": "https://cdn.example/image.png",
            },
        )

    def test_common_image_content_returns_none_without_image(self):
        self.assertIsNone(build_single_image_content(None))


if __name__ == "__main__":
    unittest.main()
