import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.explanation import (
    EXPLANATION_PROMPT_ID,
    EXPLANATION_PROMPT_VERSION,
    build_explanation_option_label,
    build_explanation_prompt,
    explain_target,
    format_explanation_response_for_discord,
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
        self.assertEqual(EXPLANATION_PROMPT_VERSION, "3")

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


class ExplanationFormatTests(unittest.TestCase):
    def test_format_explanation_response_converts_labeled_output_to_markdown(self):
        formatted = format_explanation_response_for_discord(
            "Summary: Discord 컨텍스트 메뉴 화면입니다. "
            "Details: 오른쪽 메뉴에는 메시지 번역과 설명 같은 봇 명령이 있습니다. "
            "Context: 메시지에 바로 실행하는 기능입니다."
        )

        self.assertEqual(
            formatted,
            "**요약**\n"
            "Discord 컨텍스트 메뉴 화면입니다.\n\n"
            "**설명**\n"
            "오른쪽 메뉴에는 메시지 번역과 설명 같은 봇 명령이 있습니다.\n\n"
            "**맥락**\n"
            "메시지에 바로 실행하는 기능입니다.",
        )

    def test_format_explanation_response_keeps_existing_markdown(self):
        response = "**요약**\n이미 구조화된 설명입니다."

        self.assertEqual(format_explanation_response_for_discord(response), response)

    def test_format_explanation_response_wraps_plain_text(self):
        formatted = format_explanation_response_for_discord(
            "이 문장은 배포 환경 설정이 섞였다는 뜻입니다."
        )

        self.assertEqual(
            formatted,
            "**설명**\n이 문장은 배포 환경 설정이 섞였다는 뜻입니다.",
        )


class ExplanationTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_explain_target_sends_raw_target_message_and_formats_response(self):
        captured_kwargs = {}

        def fake_custom_prompt_model(**kwargs):
            captured_kwargs.update(kwargs)
            return "Summary: 설정 혼선입니다. Details: DB_HOST 값이 맞지 않습니다."

        with patch("cogs.explanation.custom_prompt_model", fake_custom_prompt_model):
            result = await explain_target("DB_HOST가 docker로 잡혀야 한다", None)

        target_message = captured_kwargs["prompt"]["variables"]["target_message"]
        self.assertEqual(target_message, "DB_HOST가 docker로 잡혀야 한다")
        self.assertNotIn("Discord Markdown", target_message)
        self.assertEqual(
            result,
            "**요약**\n설정 혼선입니다.\n\n**설명**\nDB_HOST 값이 맞지 않습니다.",
        )


if __name__ == "__main__":
    unittest.main()
