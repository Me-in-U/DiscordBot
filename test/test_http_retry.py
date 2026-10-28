import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from common.http import fetch_text_with_retry


class HttpRetryTests(unittest.IsolatedAsyncioTestCase):
    def session(self, *errors):
        response = SimpleNamespace(
            raise_for_status=MagicMock(side_effect=list(errors)),
            text=AsyncMock(return_value="page"),
        )
        session = MagicMock()
        session.get.return_value.__aenter__ = AsyncMock(return_value=response)
        session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        return session, response

    def error(self, status, headers=None):
        return aiohttp.ClientResponseError(MagicMock(), (), status=status, headers=headers)

    async def test_server_error_then_success_retries_without_reading_error_body(self):
        session, response = self.session(self.error(500), None)
        with patch("common.http.asyncio.sleep", new_callable=AsyncMock) as sleep:
            self.assertEqual(await fetch_text_with_retry(session, "https://example.com"), "page")
        self.assertEqual(session.get.call_count, 2)
        response.text.assert_awaited_once()
        sleep.assert_awaited_once_with(1)

    async def test_permanent_403_is_not_retried(self):
        session, response = self.session(self.error(403))
        with self.assertRaises(aiohttp.ClientResponseError):
            await fetch_text_with_retry(session, "https://example.com")
        self.assertEqual(session.get.call_count, 1)
        response.text.assert_not_awaited()

    async def test_rate_limit_respects_retry_after(self):
        session, _ = self.session(self.error(429, {"Retry-After": "7"}), None)
        with patch("common.http.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await fetch_text_with_retry(session, "https://example.com")
        sleep.assert_awaited_once_with(7)

    async def test_long_rate_limit_is_left_for_next_poll(self):
        session, _ = self.session(self.error(429, {"Retry-After": "120"}))
        with patch("common.http.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(aiohttp.ClientResponseError):
                await fetch_text_with_retry(session, "https://example.com")
        sleep.assert_not_awaited()

    async def test_timeout_stops_after_three_attempts(self):
        session, _ = self.session(TimeoutError(), TimeoutError(), TimeoutError())
        with patch("common.http.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(TimeoutError):
                await fetch_text_with_retry(session, "https://example.com")
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [1, 2])

    async def test_cancellation_is_not_retried(self):
        session, _ = self.session(asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await fetch_text_with_retry(session, "https://example.com")
        self.assertEqual(session.get.call_count, 1)
