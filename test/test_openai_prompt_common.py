import unittest

from common.openai_prompt import (
    build_labeled_image_content,
    build_prompt,
    build_single_image_content,
)


class OpenAIPromptCommonTests(unittest.TestCase):
    def test_build_prompt_includes_id_version_and_variables(self):
        prompt = build_prompt(
            "pmpt_test",
            "2",
            {"target_message": "설명할 내용"},
        )

        self.assertEqual(
            prompt,
            {
                "id": "pmpt_test",
                "version": "2",
                "variables": {"target_message": "설명할 내용"},
            },
        )

    def test_build_prompt_omits_variables_when_not_provided(self):
        self.assertEqual(
            build_prompt("pmpt_test", "2"),
            {
                "id": "pmpt_test",
                "version": "2",
            },
        )

    def test_build_single_image_content_uses_responses_input_image_shape(self):
        payload = build_single_image_content("https://cdn.example/image.png")

        self.assertEqual(
            payload,
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "https://cdn.example/image.png",
                        }
                    ],
                },
            ],
        )

    def test_build_single_image_content_returns_none_without_image_url(self):
        self.assertIsNone(build_single_image_content(None))
        self.assertIsNone(build_single_image_content(""))

    def test_build_labeled_image_content_keeps_image_context_order(self):
        payload = build_labeled_image_content(
            [
                ("해석 대상 첨부 이미지", "https://cdn.example/target.png"),
                ("이전 메시지 첨부 이미지 1", "https://cdn.example/previous.png"),
            ]
        )

        self.assertEqual(
            payload,
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "해석 대상 첨부 이미지",
                        },
                        {
                            "type": "input_image",
                            "image_url": "https://cdn.example/target.png",
                        },
                        {
                            "type": "input_text",
                            "text": "이전 메시지 첨부 이미지 1",
                        },
                        {
                            "type": "input_image",
                            "image_url": "https://cdn.example/previous.png",
                        },
                    ],
                }
            ],
        )

    def test_build_labeled_image_content_returns_none_without_valid_images(self):
        self.assertIsNone(build_labeled_image_content([]))
        self.assertIsNone(build_labeled_image_content([("빈 이미지", "")]))


if __name__ == "__main__":
    unittest.main()
