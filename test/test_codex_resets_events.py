import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from util.codex_resets.events import refresh_codex_reset_notifications
from util.codex_resets.fetcher import CodexResetEvent, CodexResetSnapshot
from util.codex_resets.notification_state import CodexResetNotificationState


def _event(tweet_id: str, minute: int) -> CodexResetEvent:
    return CodexResetEvent(
        tweet_id=tweet_id,
        tweet_url=f"https://x.com/example/status/{tweet_id}",
        text=f"Reset {tweet_id}",
        announced_at=datetime(2026, 7, 21, tzinfo=timezone.utc)
        + timedelta(minutes=minute),
    )


class CodexResetsEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_poll_seeds_latest_event_without_sending_history(self):
        latest = _event("300", 3)
        saved = []
        sent = []

        async def save_state(guild_id, state):
            saved.append((guild_id, state))

        async def send_notification(channel, event):
            sent.append((channel, event))
            return 1

        results = await refresh_codex_reset_notifications(
            object(),
            get_channels=lambda: _async_value({10: 100}),
            fetch_snapshot=lambda: _async_value(
                CodexResetSnapshot(events=(latest, _event("200", 2)))
            ),
            load_state=lambda _guild_id: _async_value(
                CodexResetNotificationState()
            ),
            save_state=save_state,
            resolve_channel=lambda _bot, channel_id: _async_value(
                SimpleNamespace(id=channel_id)
            ),
            send_notification=send_notification,
        )

        self.assertEqual(sent, [])
        self.assertEqual(saved[0][0], 10)
        self.assertEqual(saved[0][1].last_tweet_id, "300")
        self.assertEqual(results[0].status, "skipped")
        self.assertEqual(results[0].action, "seeded")

    async def test_sends_all_unseen_events_oldest_first_and_advances_state(self):
        latest = _event("300", 3)
        middle = _event("200", 2)
        previous = _event("100", 1)
        saved = []
        sent_ids = []

        async def save_state(_guild_id, state):
            saved.append(state)

        async def send_notification(_channel, event):
            sent_ids.append(event.tweet_id)
            return int(event.tweet_id)

        results = await refresh_codex_reset_notifications(
            object(),
            get_channels=lambda: _async_value({10: 100}),
            fetch_snapshot=lambda: _async_value(
                CodexResetSnapshot(events=(latest, middle, previous))
            ),
            load_state=lambda _guild_id: _async_value(
                CodexResetNotificationState(last_tweet_id="100")
            ),
            save_state=save_state,
            resolve_channel=lambda _bot, channel_id: _async_value(
                SimpleNamespace(id=channel_id)
            ),
            send_notification=send_notification,
        )

        self.assertEqual(sent_ids, ["200", "300"])
        self.assertEqual(
            [state.last_tweet_id for state in saved],
            ["200", "300"],
        )
        self.assertEqual([result.action for result in results], ["sent", "sent"])

    async def test_unknown_old_state_reseeds_without_flooding(self):
        latest = _event("300", 3)
        saved = []

        async def save_state(_guild_id, state):
            saved.append(state)

        results = await refresh_codex_reset_notifications(
            object(),
            get_channels=lambda: _async_value({10: 100}),
            fetch_snapshot=lambda: _async_value(
                CodexResetSnapshot(events=(latest, _event("200", 2)))
            ),
            load_state=lambda _guild_id: _async_value(
                CodexResetNotificationState(last_tweet_id="expired")
            ),
            save_state=save_state,
            resolve_channel=lambda _bot, channel_id: _async_value(
                SimpleNamespace(id=channel_id)
            ),
            send_notification=lambda _channel, _event: _async_value(1),
        )

        self.assertEqual(saved[0].last_tweet_id, "300")
        self.assertEqual(results[0].action, "state_reseeded")

    async def test_skips_fetch_when_no_channels_are_configured(self):
        fetched = []

        async def fetch_snapshot():
            fetched.append(True)
            return CodexResetSnapshot(events=())

        results = await refresh_codex_reset_notifications(
            object(),
            get_channels=lambda: _async_value({}),
            fetch_snapshot=fetch_snapshot,
        )

        self.assertEqual(results, [])
        self.assertEqual(fetched, [])


async def _async_value(value):
    return value


if __name__ == "__main__":
    unittest.main()
