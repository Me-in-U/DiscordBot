import asyncio
import struct
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from util.minecraft_rcon import _read_packet, add_whitelist_player


def packet(request_id, kind, text=""):
    payload = struct.pack("<ii", request_id, kind) + text.encode() + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


class MinecraftRconTests(unittest.IsolatedAsyncioTestCase):
    async def invoke_rcon(self, reply, username="Steve"):
        reader = asyncio.StreamReader()
        reader.feed_data(reply)
        reader.feed_eof()
        writer = MagicMock()
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        self.writer = writer
        environment = {
            "MINECRAFT_RCON_HOST": "192.0.2.10",
            "MINECRAFT_RCON_PORT": "25575",
            "MINECRAFT_RCON_PASSWORD": "test-password",
        }
        with patch.dict("os.environ", environment):
            with patch("util.minecraft_rcon.asyncio.open_connection", new_callable=AsyncMock) as connect:
                connect.return_value = reader, writer
                result = await add_whitelist_player(username)
                connect.assert_awaited_once_with("192.0.2.10", 25575)
        return result

    async def test_authentication_and_fixed_whitelist_command(self):
        for prefix in (b"", packet(1, 0)):
            with self.subTest(empty_auth_response=bool(prefix)):
                result = await self.invoke_rcon(
                    prefix + packet(1, 2) + packet(2, 0, "Added Steve to the whitelist")
                )
                self.assertEqual(result, "Added Steve to the whitelist")
                self.assertEqual(self.writer.write.call_args_list[0].args[0], packet(1, 3, "test-password"))
                self.assertEqual(self.writer.write.call_args_list[1].args[0], packet(2, 2, "whitelist add Steve"))
                self.writer.close.assert_called_once()
                self.writer.wait_closed.assert_awaited_once()

    async def test_authentication_failure_never_sends_command(self):
        with self.assertRaisesRegex(ValueError, "authentication"):
            await self.invoke_rcon(packet(-1, 2))
        self.assertEqual(self.writer.write.call_count, 1)
        self.writer.close.assert_called_once()

    async def test_invalid_names_never_connect(self):
        with patch("util.minecraft_rcon.asyncio.open_connection", new_callable=AsyncMock) as connect:
            for username in ("ab", "a" * 17, "Steve\nstop", "Steve;op", "한글이름"):
                with self.subTest(username=username), self.assertRaises(ValueError):
                    await add_whitelist_player(username)
            connect.assert_not_awaited()

    async def test_missing_configuration_never_connects(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("util.minecraft_rcon.asyncio.open_connection", new_callable=AsyncMock) as connect:
                with self.assertRaisesRegex(ValueError, "configuration"):
                    await add_whitelist_player("Steve")
                connect.assert_not_awaited()

    async def test_malformed_or_incomplete_response_closes_connection(self):
        for reply in (packet(9, 0, "wrong id"), packet(2, 2, "wrong type"), packet(2, 0), b""):
            with self.subTest(reply=reply):
                with self.assertRaises((ValueError, asyncio.IncompleteReadError)):
                    await self.invoke_rcon(packet(1, 2) + reply)
                self.writer.close.assert_called_once()

    async def test_packet_reader_rejects_bad_lengths_and_terminators(self):
        for data in (struct.pack("<i", -1), struct.pack("<i", 4097), packet(1, 2)[:-2] + b"xx"):
            with self.subTest(data=data):
                reader = asyncio.StreamReader()
                reader.feed_data(data)
                reader.feed_eof()
                with self.assertRaises(ValueError):
                    await _read_packet(reader)


if __name__ == "__main__":
    unittest.main()
