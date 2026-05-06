import os
import unittest

os.environ.setdefault("OPENAI_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from util.message_context import (
    build_message_action_target,
    build_message_select_label,
    build_recent_message_option,
    extract_first_youtube_link,
)


class DummyAttachment:
    def __init__(
        self,
        url: str,
        content_type: str | None = None,
        filename: str = "",
    ) -> None:
        self.url = url
        self.content_type = content_type
        self.filename = filename


class DummyMessage:
    def __init__(
        self,
        content: str = "",
        attachments: list | None = None,
        message_id: int = 1,
    ) -> None:
        self.content = content
        self.attachments = attachments or []
        self.id = message_id


class MessageContextActionTests(unittest.TestCase):
    def test_builds_target_from_text_and_image_attachment(self):
        target = build_message_action_target(
            DummyMessage(
                "  hello  ",
                [DummyAttachment("https://cdn.example/image.png", "image/png")],
            )
        )

        self.assertEqual(target.text, "hello")
        self.assertEqual(target.image_url, "https://cdn.example/image.png")
        self.assertTrue(target.has_input)

    def test_accepts_image_only_message(self):
        target = build_message_action_target(
            DummyMessage(
                "",
                [DummyAttachment("https://cdn.example/photo.jpg", "image/jpeg")],
            )
        )

        self.assertEqual(target.text, "")
        self.assertEqual(target.image_url, "https://cdn.example/photo.jpg")
        self.assertTrue(target.has_input)

    def test_ignores_non_image_attachments_without_text(self):
        target = build_message_action_target(
            DummyMessage(
                "",
                [
                    DummyAttachment(
                        "https://cdn.example/archive.zip",
                        "application/zip",
                        "archive.zip",
                    )
                ],
            )
        )

        self.assertEqual(target.text, "")
        self.assertIsNone(target.image_url)
        self.assertFalse(target.has_input)

    def test_extracts_first_youtube_link_from_message_text(self):
        self.assertEqual(
            extract_first_youtube_link(
                DummyMessage(
                    "확인 https://youtu.be/dQw4w9WgXcQ 그리고 "
                    "https://www.youtube.com/watch?v=oHg5SJYRHA0"
                )
            ),
            "https://youtu.be/dQw4w9WgXcQ",
        )

    def test_returns_none_when_message_has_no_youtube_link(self):
        self.assertIsNone(extract_first_youtube_link(DummyMessage("그냥 텍스트")))

    def test_select_label_uses_image_marker_for_image_only_message(self):
        self.assertEqual(
            build_message_select_label("", "https://cdn.example/a.png"),
            "(이미지)",
        )

    def test_select_label_uses_text_when_text_and_image_exist(self):
        self.assertEqual(
            build_message_select_label("  설명할 텍스트  ", "https://cdn.example/a.png"),
            "설명할 텍스트",
        )

    def test_build_recent_message_option_includes_image_only_message(self):
        option = build_recent_message_option(
            DummyMessage(
                "",
                [DummyAttachment("https://cdn.example/photo.jpg", "image/jpeg")],
                message_id=123,
            )
        )

        self.assertEqual(
            option,
            {
                "content": "",
                "id": 123,
                "image_url": "https://cdn.example/photo.jpg",
            },
        )

    def test_build_recent_message_option_excludes_slash_command_text(self):
        self.assertIsNone(build_recent_message_option(DummyMessage("/번역")))


if __name__ == "__main__":
    unittest.main()
