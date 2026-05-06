import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.interpret import (
    INTERPRET_PROMPT_VERSION,
    format_interpret_response_for_discord,
    interpret_target,
)


class InterpretActionTests(unittest.TestCase):
    def test_format_interpret_response_converts_labeled_output_to_markdown(self):
        formatted = format_interpret_response_for_discord(
            "Reasoning: 표면적으로는 귀가 시간이 빨라졌다는 말입니다. "
            "Conclusion: 최근 행동 변화에 대한 관찰입니다. "
            "Hidden meaning: 설명을 요구하거나 의심을 담고 있을 수 있습니다."
        )

        self.assertEqual(
            formatted,
            "**의미 분석**\n"
            "표면적으로는 귀가 시간이 빨라졌다는 말입니다.\n\n"
            "**결론**\n"
            "최근 행동 변화에 대한 관찰입니다.\n\n"
            "**숨은 의미**\n"
            "설명을 요구하거나 의심을 담고 있을 수 있습니다.",
        )

    def test_format_interpret_response_omits_hidden_section_when_absent(self):
        formatted = format_interpret_response_for_discord(
            "Reasoning: 단순한 점심 질문입니다. Conclusion: 대화 시작용 질문입니다."
        )

        self.assertEqual(
            formatted,
            "**의미 분석**\n"
            "단순한 점심 질문입니다.\n\n"
            "**결론**\n"
            "대화 시작용 질문입니다.",
        )

    def test_format_interpret_response_keeps_existing_markdown(self):
        response = "**의미 분석**\n이미 정리된 응답입니다."

        self.assertEqual(format_interpret_response_for_discord(response), response)


class InterpretTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_interpret_target_sends_raw_question_without_developer_message(self):
        captured_kwargs = {}

        def fake_custom_prompt_model(**kwargs):
            captured_kwargs.update(kwargs)
            return "Reasoning: 표면 의미입니다. Conclusion: 최종 해석입니다."

        with patch("cogs.interpret.custom_prompt_model", fake_custom_prompt_model):
            result = await interpret_target("요즘 일찍 들어오네?", None)

        target_question = captured_kwargs["prompt"]["variables"]["question"]
        self.assertEqual(target_question, "요즘 일찍 들어오네?")
        self.assertNotIn("Discord Markdown", target_question)
        self.assertEqual(captured_kwargs["prompt"]["version"], INTERPRET_PROMPT_VERSION)
        self.assertEqual(INTERPRET_PROMPT_VERSION, "10")
        self.assertEqual(
            result,
            "**의미 분석**\n표면 의미입니다.\n\n**결론**\n최종 해석입니다.",
        )

    async def test_interpret_target_sends_image_fallback_without_format_instruction(self):
        captured_kwargs = {}

        def fake_custom_prompt_model(**kwargs):
            captured_kwargs.update(kwargs)
            return "Reasoning: 이미지 맥락입니다."

        with patch("cogs.interpret.custom_prompt_model", fake_custom_prompt_model):
            await interpret_target("   ", "https://cdn.example/image.png")

        target_question = captured_kwargs["prompt"]["variables"]["question"]
        self.assertEqual(target_question, "첨부 이미지를 해석해줘.")
        self.assertNotIn("Discord Markdown", target_question)


if __name__ == "__main__":
    unittest.main()
