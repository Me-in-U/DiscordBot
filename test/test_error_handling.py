import logging
import os
import unittest

from util.logging_utils import log_user_error, user_error_message

os.environ.setdefault("OPENAI_KEY", "test-key")


class ErrorHandlingHelperTests(unittest.TestCase):
    def test_user_error_message_does_not_include_raw_exception(self):
        message = user_error_message("검색", RuntimeError("secret-token HTTP 500"))

        self.assertIn("검색", message)
        self.assertIn("오류가 발생했습니다", message)
        self.assertNotIn("secret-token", message)
        self.assertNotIn("HTTP 500", message)
        self.assertNotIn("RuntimeError", message)
        self.assertNotIn("Error:", message)

    def test_log_user_error_logs_stack_and_returns_safe_message(self):
        logger = logging.getLogger("test.error_handling")

        with self.assertLogs(logger, level="ERROR") as captured:
            try:
                raise RuntimeError("secret-token")
            except RuntimeError as exc:
                message = log_user_error(logger, "번역", exc)

        self.assertIn("번역", message)
        self.assertNotIn("secret-token", message)
        self.assertIn("번역", "\n".join(captured.output))
        self.assertIn("secret-token", "\n".join(captured.output))

    def test_openai_model_error_returns_admin_contact_message(self):
        from api.chatGPT import OpenAIModelError

        message = user_error_message(
            "검색",
            OpenAIModelError("OpenAI prompt response failed."),
        )

        self.assertIn("검색", message)
        self.assertIn("관리자에게 연락해주세요", message)
        self.assertNotIn("잠시 후 다시 시도", message)
        self.assertNotIn("OpenAI", message)

    def test_nested_openai_model_error_returns_admin_contact_message(self):
        from api.chatGPT import OpenAIModelError

        try:
            try:
                raise OpenAIModelError("OpenAI prompt response failed.")
            except OpenAIModelError as exc:
                raise RuntimeError("wrapper-secret") from exc
        except RuntimeError as exc:
            message = user_error_message("유튜브 요약", exc)

        self.assertIn("유튜브 요약", message)
        self.assertIn("관리자에게 연락해주세요", message)
        self.assertNotIn("잠시 후 다시 시도", message)
        self.assertNotIn("wrapper-secret", message)


if __name__ == "__main__":
    unittest.main()
