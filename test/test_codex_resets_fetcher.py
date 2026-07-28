import unittest
from datetime import datetime, timezone

from util.codex_resets.fetcher import (
    CodexResetEvent,
    fetch_codex_reset_snapshot,
    parse_codex_resets_payload,
)


class CodexResetsFetcherTests(unittest.IsolatedAsyncioTestCase):
    def test_parses_and_sorts_reset_events_newest_first(self):
        snapshot = parse_codex_resets_payload(
            {
                "events": [
                    {
                        "tweet_id": "100",
                        "tweet_url": "https://x.com/example/status/100",
                        "text": "Older reset",
                        "announced_at": "2026-07-20T00:00:00Z",
                    },
                    {
                        "tweet_id": "200",
                        "tweet_url": "https://x.com/example/status/200",
                        "text": "Newer reset",
                        "announced_at": "2026-07-21T00:00:00Z",
                    },
                ],
                "generated_at": "2026-07-21T00:01:00Z",
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
                    "events": [
                        {
                            "tweet_id": "100",
                            "tweet_url": "",
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
                "events": [
                    {
                        "tweet_id": "300",
                        "tweet_url": "https://x.com/example/status/300",
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
