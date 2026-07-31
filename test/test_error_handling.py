import logging
import os
import unittest

from util.logging_utils import (
    KoreaStandardTimeFormatter,
    configure_logging,
    log_user_error,
    user_error_message,
)

os.environ.setdefault("OPENAI_KEY", "test-key")


class ErrorHandlingHelperTests(unittest.TestCase):
    def test_voice_receive_protocol_noise_is_hidden_at_info_level(self):
        logger_names = (
            "discord.ext.voice_recv.gateway",
            "discord.ext.voice_recv.reader",
        )
        original_levels = {
            name: logging.getLogger(name).level for name in logger_names
        }

        try:
            configure_logging()
            for logger_name in logger_names:
                self.assertEqual(
                    logging.WARNING,
                    logging.getLogger(logger_name).level,
                )
        finally:
            for logger_name, original_level in original_levels.items():
                logging.getLogger(logger_name).setLevel(original_level)

    def test_log_formatter_uses_korea_standard_time(self):
        formatter = KoreaStandardTimeFormatter("%(asctime)s %(message)s")
        record = logging.LogRecord(
            "test",
            logging.INFO,
            __file__,
            1,
            "message",
            (),
            None,
        )
        record.created = 0

        formatted = formatter.format(record)

        self.assertTrue(formatted.startswith("1970-01-01 09:00:00"))

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
