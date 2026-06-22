import unittest
from pathlib import Path
from types import SimpleNamespace

from util.message.recent import get_recent_messages


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


if __name__ == "__main__":
    unittest.main()
