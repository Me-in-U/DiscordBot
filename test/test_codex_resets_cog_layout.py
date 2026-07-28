import unittest
from pathlib import Path


COG_PATH = Path("cogs/codex_resets/__init__.py")
LOOP_PATH = Path("cogs/loop/__init__.py")
CHANNEL_SETTINGS_PATH = Path("cogs/channel_settings/__init__.py")
HELP_PATH = Path("cogs/custom_help/__init__.py")
README_PATH = Path("README.md")


class CodexResetsCogLayoutTests(unittest.TestCase):
    def test_exposes_subscription_command_and_channel_setting(self):
        cog_source = COG_PATH.read_text(encoding="utf-8")
        channel_source = CHANNEL_SETTINGS_PATH.read_text(encoding="utf-8")

        self.assertIn('name="코덱스리셋알림"', cog_source)
        self.assertIn("seed_codex_reset_state_for_guild", cog_source)
        self.assertIn('"codex_reset": "코덱스리셋"', channel_source)
        self.assertIn(
            'app_commands.Choice(name="코덱스리셋", value="codex_reset")',
            channel_source,
        )

    def test_registers_three_minute_polling_loop(self):
        loop_source = LOOP_PATH.read_text(encoding="utf-8")

        self.assertIn('"codex_reset_notification_check"', loop_source)
        self.assertIn("async def codex_reset_notification_check", loop_source)
        self.assertIn("@tasks.loop(minutes=3)", loop_source)
        self.assertIn("run_codex_reset_notification_loop", loop_source)

    def test_help_and_readme_document_codex_reset_notifications(self):
        help_source = HELP_PATH.read_text(encoding="utf-8")
        readme_source = README_PATH.read_text(encoding="utf-8")

        self.assertIn("/코덱스리셋알림", help_source)
        self.assertIn("코덱스리셋", help_source)
        self.assertIn("/코덱스리셋알림", readme_source)
        self.assertIn("3분", readme_source)


if __name__ == "__main__":
    unittest.main()
