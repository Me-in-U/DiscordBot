import ast
import unittest
from pathlib import Path

from util.youtube_subscriptions import YouTubeSubscription, row_to_subscription


YOUTUBE_SUBSCRIPTION_COG_PATH = Path("cogs/youtube_subscriptions.py")
PUBLIC_COMMAND_METHODS = {
    "add_subscription",
    "delete_subscription",
    "list_subscription",
}


def _is_ephemeral_true(keyword: ast.keyword) -> bool:
    return (
        keyword.arg == "ephemeral"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
    )


class YouTubeSubscriptionTests(unittest.TestCase):
    def test_subscription_command_messages_are_public(self):
        tree = ast.parse(
            YOUTUBE_SUBSCRIPTION_COG_PATH.read_text(encoding="utf-8"),
            filename=str(YOUTUBE_SUBSCRIPTION_COG_PATH),
        )
        failures: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if node.name not in PUBLIC_COMMAND_METHODS:
                continue

            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                if any(_is_ephemeral_true(keyword) for keyword in call.keywords):
                    failures.append(f"{node.name}:{call.lineno}")

        self.assertEqual(failures, [])

    def test_row_to_subscription_decodes_json_state(self):
        row = {
            "id": 7,
            "guild_id": 123,
            "channel_name": "침착맨 플러스",
            "channel_id": "UC1234567890123456789012",
            "channel_handle": "@ChimChakMan_Data",
            "source_input": "@ChimChakMan_Data",
            "websub_subscribed_at": "2026-05-06T00:52:20+00:00",
            "websub_lease_seconds": 604800,
            "pending_videos": '{"VIDEO1":{"title":"예정 방송"}}',
            "notified_video_ids": '["VIDEO0"]',
        }

        subscription = row_to_subscription(row)

        self.assertEqual(
            subscription,
            YouTubeSubscription(
                id=7,
                guild_id=123,
                channel_name="침착맨 플러스",
                channel_id="UC1234567890123456789012",
                channel_handle="@ChimChakMan_Data",
                source_input="@ChimChakMan_Data",
                websub_subscribed_at="2026-05-06T00:52:20+00:00",
                websub_lease_seconds=604800,
                pending_videos={"VIDEO1": {"title": "예정 방송"}},
                notified_video_ids=["VIDEO0"],
            ),
        )

    def test_row_to_subscription_uses_empty_state_defaults(self):
        subscription = row_to_subscription(
            {
                "id": 8,
                "guild_id": 123,
                "channel_name": "UC1234567890123456789012",
                "channel_id": "UC1234567890123456789012",
                "channel_handle": None,
                "source_input": "UC1234567890123456789012",
                "websub_subscribed_at": None,
                "websub_lease_seconds": None,
                "pending_videos": None,
                "notified_video_ids": None,
            }
        )

        self.assertEqual(subscription.pending_videos, {})
        self.assertEqual(subscription.notified_video_ids, [])


if __name__ == "__main__":
    unittest.main()
