import ast
import unittest
from pathlib import Path

from util.youtube_subscriptions import YouTubeSubscription, row_to_subscription


YOUTUBE_SUBSCRIPTION_COG_PATH = Path("cogs/youtube_subscriptions.py")
LEGACY_YOUTUBE_CHECKER_COG_PATH = Path("cogs/YoutubeCheckerCog.py")
CUSTOM_HELP_PATH = Path("cogs/custom_help.py")
DB_PATH = Path("util/db.py")
PUBLIC_COMMAND_METHODS = {
    "add_subscription",
    "configure_subscription_alerts",
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
    def test_add_subscription_description_mentions_search_terms(self):
        tree = ast.parse(
            YOUTUBE_SUBSCRIPTION_COG_PATH.read_text(encoding="utf-8"),
            filename=str(YOUTUBE_SUBSCRIPTION_COG_PATH),
        )
        add_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "add_subscription"
        )
        decorator_texts = [
            node.value
            for decorator in add_node.decorator_list
            for node in ast.walk(decorator)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]

        self.assertTrue(
            any("검색어" in text for text in decorator_texts),
            decorator_texts,
        )

    def test_add_subscription_accepts_live_and_upload_alert_options(self):
        tree = ast.parse(
            YOUTUBE_SUBSCRIPTION_COG_PATH.read_text(encoding="utf-8"),
            filename=str(YOUTUBE_SUBSCRIPTION_COG_PATH),
        )
        add_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "add_subscription"
        )
        arg_names = [arg.arg for arg in add_node.args.args]

        self.assertIn("live_alert_enabled", arg_names)
        self.assertIn("upload_alert_enabled", arg_names)
        self.assertIn("community_alert_enabled", arg_names)

    def test_alert_settings_command_exists(self):
        tree = ast.parse(
            YOUTUBE_SUBSCRIPTION_COG_PATH.read_text(encoding="utf-8"),
            filename=str(YOUTUBE_SUBSCRIPTION_COG_PATH),
        )
        command_names: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "name"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    command_names.append(keyword.value.value)

        self.assertIn("알림설정", command_names)

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
            "live_alert_enabled": 1,
            "upload_alert_enabled": 1,
            "upload_alert_enabled_at": "2026-05-06T01:00:00+00:00",
            "notified_upload_video_ids": '["UPLOAD0"]',
            "community_alert_enabled": 1,
            "notified_community_post_ids": '["POST0"]',
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
                live_alert_enabled=True,
                upload_alert_enabled=True,
                upload_alert_enabled_at="2026-05-06T01:00:00+00:00",
                notified_upload_video_ids=["UPLOAD0"],
                community_alert_enabled=True,
                notified_community_post_ids=["POST0"],
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
                "live_alert_enabled": None,
                "upload_alert_enabled": None,
                "upload_alert_enabled_at": None,
                "notified_upload_video_ids": None,
                "community_alert_enabled": None,
                "notified_community_post_ids": None,
            }
        )

        self.assertEqual(subscription.pending_videos, {})
        self.assertEqual(subscription.notified_video_ids, [])
        self.assertTrue(subscription.live_alert_enabled)
        self.assertFalse(subscription.upload_alert_enabled)
        self.assertIsNone(subscription.upload_alert_enabled_at)
        self.assertEqual(subscription.notified_upload_video_ids, [])
        self.assertFalse(subscription.community_alert_enabled)
        self.assertEqual(subscription.notified_community_post_ids, [])

    def test_schema_defines_alert_columns(self):
        db_source = DB_PATH.read_text(encoding="utf-8")

        self.assertIn("live_alert_enabled", db_source)
        self.assertIn("upload_alert_enabled", db_source)
        self.assertIn("upload_alert_enabled_at", db_source)
        self.assertIn("notified_upload_video_ids", db_source)
        self.assertIn("community_alert_enabled", db_source)
        self.assertIn("notified_community_post_ids", db_source)

    def test_alert_settings_can_leave_only_community_enabled(self):
        source = Path("util/youtube_subscriptions.py").read_text(encoding="utf-8")

        self.assertIn("community_alert_enabled", source)
        self.assertIn(
            "if not live_alert_enabled and not upload_alert_enabled and not community_alert_enabled",
            source,
        )

    def test_help_mentions_upload_alert_and_alert_settings(self):
        help_source = CUSTOM_HELP_PATH.read_text(encoding="utf-8")

        self.assertIn("/유튜브구독 알림설정", help_source)
        self.assertIn("영상 알림", help_source)
        self.assertIn("커뮤니티 알림", help_source)

    def test_legacy_live_checker_cog_is_removed(self):
        self.assertFalse(LEGACY_YOUTUBE_CHECKER_COG_PATH.exists())


if __name__ == "__main__":
    unittest.main()
