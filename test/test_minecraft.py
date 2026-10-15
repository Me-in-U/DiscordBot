import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.minecraft import MinecraftCommands, STATUS_API_URL


class MinecraftCommandTests(unittest.IsolatedAsyncioTestCase):
    async def invoke_command(self, payload=None, error=None):
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        response = MagicMock()
        response.json = AsyncMock(return_value=payload)
        response.raise_for_status.side_effect = error
        request = MagicMock()
        request.__aenter__ = AsyncMock(return_value=response)
        request.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.get.return_value = request
        with patch("cogs.minecraft.aiohttp.ClientSession") as client:
            client.return_value.__aenter__.return_value = session
            cog = MinecraftCommands(MagicMock())
            await cog.minecraft_server.callback(cog, interaction)
            session.get.assert_called_once_with(STATUS_API_URL)
            self.assertEqual(client.call_args.kwargs["timeout"].total, 10)
            self.assertTrue(client.call_args.kwargs["headers"]["User-Agent"])
        interaction.response.defer.assert_awaited_once_with(thinking=True)
        interaction.followup.send.assert_awaited_once()
        self.assertEqual(set(interaction.followup.send.call_args.kwargs), {"embed"})
        embed = interaction.followup.send.call_args.kwargs["embed"]
        self.assertIn("mc.ios.kr", embed.description)
        guide = embed.fields[-1].value
        for text in (
            "https://fabricmc.net/use/installer/",
            "https://modrinth.com/mod/sodium/versions?g=26.3",
            "https://modrinth.com/mod/iris/versions?g=26.3",
            "mc26.3-x.x.x-fabric", "x.x.x+26.3-fabric",
            ".minecraft/mods", "Fabric 26.3",
        ):
            self.assertIn(text, guide)
        self.assertIn("5분", embed.footer.text)
        return {field.name: field.value for field in embed.fields}

    async def test_online_status_and_guide_share_one_embed(self):
        fields = await self.invoke_command({
            "online": True, "players": {"online": 3, "max": 20}, "version": "26.3",
        })
        self.assertEqual(fields["상태"], "🟢 온라인")
        self.assertEqual(fields["접속 인원"], "3 / 20명")
        self.assertEqual(fields["서버 버전"], "26.3")

    async def test_offline_status_keeps_guide(self):
        fields = await self.invoke_command({"online": False})
        self.assertEqual(fields["상태"], "🔴 오프라인")
        self.assertNotIn("접속 인원", fields)

    async def test_missing_optional_online_details(self):
        fields = await self.invoke_command({"online": True})
        self.assertEqual(fields["접속 인원"], "? / ?명")
        self.assertEqual(fields["서버 버전"], "확인 불가")

    async def test_timeout_keeps_guide_without_claiming_offline(self):
        with self.assertLogs("cogs.minecraft", level="ERROR"):
            fields = await self.invoke_command(error=asyncio.TimeoutError())
        self.assertIn("조회 실패", fields["상태"])
        self.assertNotIn("오프라인", fields["상태"])

    async def test_invalid_response_keeps_guide(self):
        for payload in ([], {}, {"online": "false"}, {"online": True, "players": []}):
            with self.subTest(payload=payload):
                with self.assertLogs("cogs.minecraft", level="ERROR"):
                    fields = await self.invoke_command(payload)
                self.assertIn("조회 실패", fields["상태"])


if __name__ == "__main__":
    unittest.main()
