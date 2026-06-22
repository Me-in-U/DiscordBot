import unittest
from pathlib import Path


YOUTUBE_WEBSUB_RENEWAL_PATH = Path("util/youtube/websub_renewal.py")
LEGACY_YOUTUBE_WEBSUB_RENEWAL_PATH = Path("util/youtube_websub_renewal.py")


class _FakeWebSubOwner:
    def __init__(self, result: bool):
        self.result = result
        self.calls = 0

    async def ensure_youtube_websub_subscription(self) -> bool:
        self.calls += 1
        return self.result


class YouTubeWebSubRenewalTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_websub_renewal_lives_under_youtube_package(self):
        self.assertTrue(YOUTUBE_WEBSUB_RENEWAL_PATH.exists())
        self.assertFalse(LEGACY_YOUTUBE_WEBSUB_RENEWAL_PATH.exists())

    async def test_renews_subscription_and_logs_when_request_is_sent(self):
        from util.youtube.websub_renewal import run_youtube_websub_renewal

        logs: list[str] = []
        owner = _FakeWebSubOwner(True)

        renewed = await run_youtube_websub_renewal(owner, log=logs.append)

        self.assertTrue(renewed)
        self.assertEqual(owner.calls, 1)
        self.assertEqual(logs, ["YouTube WebSub 구독 갱신 요청 완료"])

    async def test_skips_success_log_when_no_subscription_request_is_sent(self):
        from util.youtube.websub_renewal import run_youtube_websub_renewal

        logs: list[str] = []
        owner = _FakeWebSubOwner(False)

        renewed = await run_youtube_websub_renewal(owner, log=logs.append)

        self.assertFalse(renewed)
        self.assertEqual(owner.calls, 1)
        self.assertEqual(logs, [])
