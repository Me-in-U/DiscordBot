import asyncio
from contextlib import suppress
import re
import struct

from util.env_utils import getenv_clean


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, int, str]:
    size = struct.unpack("<i", await reader.readexactly(4))[0]
    if not 10 <= size <= 4096:
        raise ValueError("Invalid RCON packet length")
    packet = await reader.readexactly(size)
    if packet[-2:] != b"\x00\x00":
        raise ValueError("Invalid RCON packet terminator")
    request_id, kind = struct.unpack("<ii", packet[:8])
    return request_id, kind, packet[8:-2].decode("utf-8", errors="replace")


async def _send_packet(writer, request_id: int, kind: int, text: str) -> None:
    payload = struct.pack("<ii", request_id, kind) + text.encode("utf-8") + b"\x00\x00"
    writer.write(struct.pack("<i", len(payload)) + payload)
    await writer.drain()


async def add_whitelist_player(username: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_]{3,16}", username) is None:
        raise ValueError("Invalid Minecraft username")
    host = getenv_clean("MINECRAFT_RCON_HOST")
    password = getenv_clean("MINECRAFT_RCON_PASSWORD")
    port = int(getenv_clean("MINECRAFT_RCON_PORT", "25575"))
    if not host or not password or "\x00" in password or not 1 <= port <= 65535:
        raise ValueError("Minecraft RCON configuration is missing or invalid")

    async with asyncio.timeout(10):
        reader, writer = await asyncio.open_connection(host, port)
        try:
            await _send_packet(writer, 1, 3, password)
            request_id, kind, _ = await _read_packet(reader)
            # Some RCON servers send an empty response before the auth result.
            if request_id == 1 and kind == 0:
                request_id, kind, _ = await _read_packet(reader)
            if request_id != 1 or kind != 2:
                raise ValueError("Minecraft RCON authentication failed")
            await _send_packet(writer, 2, 2, f"whitelist add {username}")
            request_id, kind, response = await _read_packet(reader)
            if request_id != 2 or kind != 0:
                raise ValueError("Invalid Minecraft RCON command response")
            # shortcut: whitelist add has a short reply; collect fragments if longer commands are added.
            if not response.strip() or len(response.encode("utf-8")) >= 4000:
                raise ValueError("Incomplete Minecraft whitelist response")
            return response
        finally:
            writer.close()
            with suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), timeout=2)
