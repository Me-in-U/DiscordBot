import unittest
from pathlib import Path
from types import SimpleNamespace

from util.message.recent import get_recent_message_images, get_recent_messages


RECENT_MESSAGES_PATH = Path("util/message/recent.py")
LEGACY_RECENT_MESSAGES_PATH = Path("util/get_recent_messages.py")


class GetRecentMessagesTests(unittest.TestCase):
    def test_get_recent_messages_lives_under_message_package(self):
        self.assertTrue(RECENT_MESSAGES_PATH.exists())
        self.assertFalse(LEGACY_RECENT_MESSAGES_PATH.exists())

    def test_formats_recent_messages_oldest_to_newest(self):
        client = SimpleNamespace(
            USER_MESSAGES={
                123: {
                    "Alice": [
                        {
                            "role": "user",
                            "content": "second",
                            "time": "2026-06-22 10:02:00",
                        }
                    ],
                    "Bob": [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "input_text", "text": "first"},
                                {
                                    "type": "input_image",
                                    "image_url": "https://example.com/a.png",
                                },
                            ],
                            "time": "2026-06-22 10:01:00",
                        }
                    ],
                }
            }
        )

        self.assertEqual(
            get_recent_messages(client, 123, limit=2),
            "\n".join(
                [
                    "[2026-06-22 10:01:00] Bob(assistant): first (image: https://example.com/a.png)",
                    "[2026-06-22 10:02:00] Alice(user): second",
                ]
            ),
        )

    def test_returns_latest_four_labeled_images_in_chronological_order(self):
        messages = []
        for index in range(1, 6):
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": f"message {index}"},
                        {
                            "type": "input_image",
                            "image_url": f"https://example.com/{index}.png",
                        },
                    ],
                    "time": f"2026-06-22 10:0{index}:00",
                }
            )
        client = SimpleNamespace(USER_MESSAGES={123: {"Alice": messages}})

        self.assertEqual(
            get_recent_message_images(client, 123, limit=10, max_images=4),
            tuple(
                (
                    f"[2026-06-22 10:0{index}:00] Alice 메시지 첨부 이미지 1",
                    f"https://example.com/{index}.png",
                )
                for index in range(2, 6)
            ),
        )


if __name__ == "__main__":
    unittest.main()
