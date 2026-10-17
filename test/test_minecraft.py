import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.minecraft import MinecraftCommands, MinecraftGuideView, STATUS_API_URL, setup


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
        self.assertEqual(set(interaction.followup.send.call_args.kwargs), {"embed", "view"})
        embed = interaction.followup.send.call_args.kwargs["embed"]
        self.assertIn("mc.ios.kr", embed.description)
        self.assertLessEqual({field.name for field in embed.fields}, {"상태", "접속 인원", "서버 버전"})
        self.assertIn("5분", embed.footer.text)
        view = interaction.followup.send.call_args.kwargs["view"]
        self.assertIsInstance(view, MinecraftGuideView)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 1)
        self.assertEqual(view.children[0].label, "Fabric, Sodium, Iris, SEUS")
        return {field.name: field.value for field in embed.fields}

    async def test_button_sends_installation_guide_as_new_message(self):
        view = MinecraftGuideView()
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.response.edit_message = AsyncMock()
        await view.children[0].callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        interaction.response.edit_message.assert_not_awaited()
        self.assertEqual(set(interaction.response.send_message.call_args.kwargs), {"embed"})
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        self.assertEqual(len(embed.fields), 2)
        guide = next(field.value for field in embed.fields if field.name == "FPS 향상, 렉 감소, 셰이더 적용")
        for text in (
            "https://fabricmc.net/use/installer/",
            "https://modrinth.com/mod/sodium/versions?g=26.3",
            "https://modrinth.com/mod/iris/versions?g=26.3",
            "mc26.3-x.x.x-fabric", "x.x.x+26.3-fabric",
            ".minecraft/mods", "Fabric 26.3",
        ):
            self.assertIn(text, guide)
        shader_guide = embed.fields[-1].value
        self.assertEqual(embed.fields[-1].name, "SEUS PTGI 셰이더 다운로드")
        for text in (
            "https://www.9minecraft.net/seus-ptgi-shaders-pack/",
            "**E12**: E 시리즈 최종판, 화질 중심 / 무거움",
            "**HRR 2.1**: E12 기반 최적화, FPS 향상 / 비교적 가벼움",
            "**HRR 3.0**: 광원, 반사, 구름 개선, 추적 범위 확대 / HRR 2.1보다 무거움",
            ".minecraft/shaderpacks", "압축 해제하지 않고", "비디오 설정",
        ):
            self.assertIn(text, shader_guide)
    async def test_setup_registers_persistent_guide_button(self):
        bot = MagicMock()
        bot.add_cog = AsyncMock()
        await setup(bot)
        bot.add_cog.assert_awaited_once()
        bot.add_view.assert_called_once()
        view = bot.add_view.call_args.args[0]
        self.assertIsInstance(view, MinecraftGuideView)
        self.assertTrue(view.is_persistent())

    async def test_online_status_has_guide_button(self):
        fields = await self.invoke_command({
            "online": True, "players": {"online": 3, "max": 20}, "version": "26.3",
        })
        self.assertEqual(fields["상태"], "🟢 온라인")
        self.assertEqual(fields["접속 인원"], "3 / 20명")
        self.assertEqual(fields["서버 버전"], "26.3")

    async def test_offline_status_keeps_guide_button(self):
        fields = await self.invoke_command({"online": False})
        self.assertEqual(fields["상태"], "🔴 오프라인")
        self.assertNotIn("접속 인원", fields)

    async def test_missing_optional_online_details(self):
        fields = await self.invoke_command({"online": True})
        self.assertEqual(fields["접속 인원"], "? / ?명")
        self.assertEqual(fields["서버 버전"], "확인 불가")

    async def test_timeout_keeps_guide_button_without_claiming_offline(self):
        with self.assertLogs("cogs.minecraft", level="ERROR"):
            fields = await self.invoke_command(error=asyncio.TimeoutError())
        self.assertIn("조회 실패", fields["상태"])
        self.assertNotIn("오프라인", fields["상태"])

    async def test_invalid_response_keeps_guide_button(self):
        for payload in ([], {}, {"online": "false"}, {"online": True, "players": []}):
            with self.subTest(payload=payload):
                with self.assertLogs("cogs.minecraft", level="ERROR"):
                    fields = await self.invoke_command(payload)
                self.assertIn("조회 실패", fields["상태"])


if __name__ == "__main__":
    unittest.main()
