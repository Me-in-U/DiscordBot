import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from func.find1557 import find1557


class Find1557LoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_analysis_log_excludes_ocr_content(self):
        private_ocr_text = "private-document-1557"
        message = SimpleNamespace(
            attachments=[SimpleNamespace(url="https://example.com/image.png")],
            content="",
            author=SimpleNamespace(id=123),
        )

        with patch(
            "func.find1557.asyncio.to_thread",
            new=AsyncMock(
                return_value=json.dumps(
                    {
                        "exist": True,
                        "imageToText": private_ocr_text,
                        "reason": "private-reason",
                    }
                )
            ),
        ):
            with patch(
                "func.find1557.userCount",
                new=AsyncMock(),
            ) as user_count:
                with self.assertLogs("func.find1557", level="INFO") as captured:
                    await find1557(message)

        logs = "\n".join(captured.output)
        self.assertNotIn(private_ocr_text, logs)
        self.assertNotIn("private-reason", logs)
        self.assertIn(f"ocr_length={len(private_ocr_text)}", logs)
        user_count.assert_awaited_once_with(message.author, 1)


if __name__ == "__main__":
    unittest.main()
