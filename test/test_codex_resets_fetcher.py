import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from util.codex_resets.fetcher import (
    CODEX_RESETS_API_URL,
    CodexResetEvent,
    fetch_codex_reset_snapshot,
    parse_codex_resets_payload,
)


class CodexResetsFetcherTests(unittest.IsolatedAsyncioTestCase):
    def test_observed_banked_reset_without_post_uses_tracker_link(self):
        snapshot = parse_codex_resets_payload({
            "data": [{
                "id": "observed-20260929T190000Z",
                "reset_type": "banked",
                "announced_at": "2026-09-29T19:00:00Z",
                "text": "Banked reset observed",
                "source": {"type": "observed"},
            }],
            "meta": {"generated_at": "2026-09-29T19:01:00Z"},
        })
        event = snapshot.events[0]
        self.assertEqual(event.tweet_id, "observed-20260929T190000Z")
        self.assertEqual(event.tweet_url, "https://codex-resets.com/")
        self.assertEqual(event.reset_type, "banked")

    def test_rejects_invalid_v1_payloads(self):
        event = {
            "id": "100",
            "reset_type": "regular",
            "announced_at": "2026-07-20T00:00:00Z",
            "text": "Reset",
            "source": {"type": "x_post", "url": "https://x.com/example/status/100"},
        }
        for invalid in (
            {"source": {"type": "x_post", "url": "https://x.com.evil.test/100"}},
            {"source": {"type": "observed", "url": "javascript:alert(1)"}},
            {"source": {"type": "unknown"}},
            {"reset_type": "scheduled"},
            {"announced_at": "invalid"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_codex_resets_payload({"data": [event | invalid], "meta": {}})
        for payload in ({"events": []}, {"data": []}, {"data": {}, "meta": {}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_codex_resets_payload(payload)

    def test_empty_reset_list_and_duplicate_ids(self):
        self.assertEqual(parse_codex_resets_payload({"data": [], "meta": {}}).events, ())
        event = {
            "id": "100", "reset_type": "regular",
            "announced_at": "2026-07-20T00:00:00Z", "text": "Reset",
            "source": {"type": "observed", "url": "https://x.com/example/status/100"},
        }
        snapshot = parse_codex_resets_payload({"data": [event, event], "meta": {}})
        self.assertEqual(len(snapshot.events), 1)
        self.assertEqual(snapshot.events[0].tweet_url, event["source"]["url"])

    async def test_requests_documented_v1_endpoint_and_propagates_http_errors(self):
        response = MagicMock()
        response.json = AsyncMock(return_value={"data": [], "meta": {}})
        request = MagicMock()
        request.__aenter__ = AsyncMock(return_value=response)
        session = MagicMock()
        session.get.return_value = request
        with patch("util.codex_resets.fetcher.aiohttp.ClientSession") as client:
            client.return_value.__aenter__.return_value = session
            snapshot = await fetch_codex_reset_snapshot()
            self.assertEqual(snapshot.events, ())
            self.assertEqual(CODEX_RESETS_API_URL, "https://codex-resets.com/api/v1/resets")
            self.assertEqual(session.get.call_args.args, (CODEX_RESETS_API_URL,))
            self.assertEqual(session.get.call_args.kwargs["params"], {"limit": 100, "order": "desc"})
            response.raise_for_status.side_effect = aiohttp.ClientResponseError(
                request_info=MagicMock(), history=(), status=429,
            )
            with self.assertRaises(aiohttp.ClientResponseError) as error:
                await fetch_codex_reset_snapshot()
            self.assertEqual(error.exception.status, 429)
            response.json.assert_awaited_once()

    def test_parses_and_sorts_reset_events_newest_first(self):
        snapshot = parse_codex_resets_payload(
            {
                "meta": {"generated_at": "2026-07-21T00:01:00Z"},
                "data": [
                    {
                        "id": "100",
                        "reset_type": "regular",
                        "source": {"type": "x_post", "author": "thsottiaux", "url": "https://x.com/example/status/100"},
                        "text": "Older reset",
                        "announced_at": "2026-07-20T00:00:00Z",
                    },
                    {
                        "id": "200",
                        "reset_type": "regular",
                        "source": {"type": "x_post", "author": "thsottiaux", "url": "https://x.com/example/status/200"},
                        "text": "Newer reset",
                        "announced_at": "2026-07-21T00:00:00Z",
                    },
                ],
            }
        )

        self.assertEqual(
            snapshot.events,
            (
                CodexResetEvent(
                    tweet_id="200",
                    tweet_url="https://x.com/example/status/200",
                    text="Newer reset",
                    announced_at=datetime(
                        2026,
                        7,
                        21,
                        tzinfo=timezone.utc,
                    ),
                ),
                CodexResetEvent(
                    tweet_id="100",
                    tweet_url="https://x.com/example/status/100",
                    text="Older reset",
                    announced_at=datetime(
                        2026,
                        7,
                        20,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
        )
        self.assertEqual(
            snapshot.generated_at,
            datetime(2026, 7, 21, 0, 1, tzinfo=timezone.utc),
        )

    def test_rejects_malformed_event_payload(self):
        with self.assertRaises(ValueError):
            parse_codex_resets_payload(
                {
                    "meta": {"generated_at": "2026-07-21T00:01:00Z"},
                    "data": [
                        {
                            "id": "100",
                            "reset_type": "regular",
                            "source": {"type": "x_post", "author": "thsottiaux", "url": ""},
                            "text": "Reset",
                            "announced_at": "2026-07-20T00:00:00Z",
                        }
                    ]
                }
            )

    async def test_fetches_snapshot_through_injected_json_loader(self):
        calls = []

        async def fetch_json():
            calls.append(True)
            return {
                "meta": {"generated_at": "2026-07-21T00:01:00Z"},
                "data": [
                    {
                        "id": "300",
                        "reset_type": "regular",
                        "source": {"type": "x_post", "author": "thsottiaux", "url": "https://x.com/example/status/300"},
                        "text": "Reset complete",
                        "announced_at": "2026-07-22T00:00:00Z",
                    }
                ]
            }

        snapshot = await fetch_codex_reset_snapshot(fetch_json=fetch_json)

        self.assertEqual(calls, [True])
        self.assertEqual(snapshot.events[0].tweet_id, "300")


if __name__ == "__main__":
    unittest.main()
