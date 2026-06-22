import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from util.guild.channel_settings import get_channel, get_channels_by_purpose


GUILD_CHANNEL_SETTINGS_PATH = Path("util/guild/channel_settings.py")
LEGACY_CHANNEL_SETTINGS_PATH = Path("util/channel_settings.py")


class GuildChannelSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_settings_lives_under_guild_package(self):
        self.assertTrue(GUILD_CHANNEL_SETTINGS_PATH.exists())
        self.assertFalse(LEGACY_CHANNEL_SETTINGS_PATH.exists())

    async def test_get_channel_returns_integer_channel_id(self):
        with patch(
            "util.guild.channel_settings.fetch_one",
            new=AsyncMock(return_value={"channel_id": "1234"}),
        ) as fetch_one:
            channel_id = await get_channel(10, "music")

        self.assertEqual(channel_id, 1234)
        fetch_one.assert_awaited_once()

    async def test_get_channels_by_purpose_skips_invalid_rows(self):
        with patch(
            "util.guild.channel_settings.fetch_all",
            new=AsyncMock(
                return_value=[
                    {"guild_id": "1", "channel_id": "100"},
                    {"guild_id": "bad", "channel_id": "200"},
                ]
            ),
        ):
            channels = await get_channels_by_purpose("celebration")

        self.assertEqual(channels, {1: 100})


if __name__ == "__main__":
    unittest.main()
