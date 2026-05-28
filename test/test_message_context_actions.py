import os
import unittest

os.environ.setdefault("OPENAI_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from util.message_context import (
    build_surrounding_message_context,
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


class DummyAuthor:
    def __init__(self, author_id: int, display_name: str) -> None:
        self.id = author_id
        self.display_name = display_name


class DummyMessage:
    def __init__(
        self,
        content: str = "",
        attachments: list | None = None,
        message_id: int = 1,
        author: DummyAuthor | None = None,
    ) -> None:
        self.content = content
        self.attachments = attachments or []
        self.id = message_id
        self.author = author or DummyAuthor(1, "User")
        self.channel = None


class DummyChannel:
    def __init__(self, messages: list[DummyMessage]) -> None:
        self.messages = messages
        for message in self.messages:
            message.channel = self

    async def history(
        self,
        *,
        limit: int | None = None,
        before: DummyMessage | None = None,
        after: DummyMessage | None = None,
        oldest_first: bool | None = None,
    ):
        messages = self.messages
        if before is not None:
            messages = [message for message in messages if message.id < before.id]
        if after is not None:
            messages = [message for message in messages if message.id > after.id]

        if not oldest_first:
            messages = list(reversed(messages))
        if limit is not None:
            messages = messages[:limit]

        for message in messages:
            yield message


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


class SurroundingMessageContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_surrounding_context_uses_closest_ten_messages_each_side(self):
        author = DummyAuthor(1, "Alice")
        target = DummyMessage("해석할 대상", message_id=20, author=author)
        messages = [
            *[
                DummyMessage(f"이전 {index}", message_id=index, author=author)
                for index in range(1, 13)
            ],
            target,
            *[
                DummyMessage(f"이후 {index}", message_id=index, author=author)
                for index in range(21, 34)
            ],
        ]
        DummyChannel(messages)

        context = await build_surrounding_message_context(target)

        self.assertEqual(
            context.previous_messages,
            "\n".join(f"Alice: 이전 {index}" for index in range(3, 13)),
        )
        self.assertEqual(
            context.following_messages,
            "\n".join(f"Alice: 이후 {index}" for index in range(21, 31)),
        )

    async def test_build_surrounding_context_skips_bot_and_command_messages(self):
        user = DummyAuthor(1, "Alice")
        bot = DummyAuthor(2, "Bot")
        target = DummyMessage("설명할 대상", message_id=5, author=user)
        DummyChannel(
            [
                DummyMessage("이전 정상", message_id=1, author=user),
                DummyMessage("/해석", message_id=2, author=user),
                DummyMessage("봇 응답", message_id=3, author=bot),
                target,
                DummyMessage("이후 정상", message_id=6, author=user),
                DummyMessage("봇 후속", message_id=7, author=bot),
            ]
        )

        context = await build_surrounding_message_context(target, bot_user=bot)

        self.assertEqual(context.previous_messages, "Alice: 이전 정상")
        self.assertEqual(context.following_messages, "Alice: 이후 정상")


if __name__ == "__main__":
    unittest.main()
