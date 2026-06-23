import unittest

from util.music.logging import (
    build_music_play_command_debug_message,
    log_music_debug,
    make_music_debug_logger,
)


class FakeLogger:
    def __init__(self, *, fail_first_debug: bool = False):
        self.fail_first_debug = fail_first_debug
        self.calls = []

    def debug(self, message, *args, **kwargs):
        self.calls.append((message, args, kwargs))
        if self.fail_first_debug and len(self.calls) == 1:
            raise OSError("debug sink unavailable")


class MusicLoggingTests(unittest.TestCase):
    def test_builds_play_command_debug_message(self):
        self.assertEqual(
            build_music_play_command_debug_message(
                url="https://youtu.be/example",
                guild_id=123,
                user_id=456,
            ),
            "_play: called url=https://youtu.be/example guild=123 user=456",
        )

    def test_music_debug_logger_uses_music_prefix(self):
        logger = FakeLogger()

        log_music_debug(logger, "play started")

        self.assertEqual(logger.calls, [("[MUSIC] %s", ("play started",), {})])

    def test_music_debug_logger_records_sink_failures(self):
        logger = FakeLogger(fail_first_debug=True)

        log_music_debug(logger, "play started")

        self.assertEqual(logger.calls[0], ("[MUSIC] %s", ("play started",), {}))
        self.assertEqual(
            logger.calls[1],
            ("music debug 출력 실패", (), {"exc_info": True}),
        )

    def test_make_music_debug_logger_returns_callable_bound_to_logger(self):
        logger = FakeLogger()
        debug = make_music_debug_logger(logger)

        debug("queue updated")

        self.assertEqual(logger.calls, [("[MUSIC] %s", ("queue updated",), {})])


if __name__ == "__main__":
    unittest.main()
