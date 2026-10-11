import asyncio
import threading
import unittest
from collections import deque
from unittest.mock import patch

import discord

from util.music.audio import prepare_opus_source


class FakeSource(discord.AudioSource):
    def __init__(self, packets):
        self.packets = deque(packets)
        self.cleaned = False
        self.read_threads = []

    def read(self):
        self.read_threads.append(threading.get_ident())
        return self.packets.popleft() if self.packets else b""

    def is_opus(self):
        return True

    def cleanup(self):
        self.cleaned = True


class BlockingSource(FakeSource):
    def __init__(self):
        super().__init__([])
        self.started = threading.Event()
        self.released = threading.Event()

    def read(self):
        self.started.set()
        if not self.released.wait(2):
            raise RuntimeError("test read was not released")
        return b""

    def cleanup(self):
        super().cleanup()
        self.released.set()


class MusicAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_prebuffer_preserves_all_packets_and_reads_off_event_loop(self):
        packets = [bytes([n]) for n in range(1, 13)]
        raw = FakeSource(packets)
        source = await prepare_opus_source(raw)
        self.assertEqual(len(raw.read_threads), 10)
        self.assertNotIn(threading.get_ident(), raw.read_threads)
        self.assertTrue(source.is_opus())
        self.assertEqual([source.read() for _ in packets], packets)
        self.assertEqual(source.read(), b"")
        source.cleanup()
        self.assertTrue(raw.cleaned)

    async def test_short_audio_is_preserved_and_empty_audio_is_rejected(self):
        raw = FakeSource([b"first"])
        source = await prepare_opus_source(raw)
        self.assertEqual(source.read(), b"first")
        self.assertEqual(source.read(), b"")
        empty = FakeSource([])
        with self.assertRaises(ValueError):
            await prepare_opus_source(empty)
        self.assertTrue(empty.cleaned)

    async def test_read_failure_cleans_source(self):
        raw = FakeSource([])
        with patch.object(raw, "read", side_effect=OSError("broken pipe")):
            with self.assertRaises(OSError):
                await prepare_opus_source(raw)
        self.assertTrue(raw.cleaned)

    async def test_timeout_cleans_source_and_releases_blocked_read(self):
        raw = BlockingSource()
        wait_for = asyncio.wait_for

        async def short_wait(awaitable, *, timeout):
            self.assertEqual(timeout, 15.0)
            return await wait_for(awaitable, timeout=0.05)

        with patch("util.music.audio.asyncio.wait_for", side_effect=short_wait):
            with self.assertRaises(TimeoutError):
                await prepare_opus_source(raw)
        self.assertTrue(raw.cleaned)
        self.assertTrue(raw.released.is_set())

    async def test_cancellation_cleans_source_and_releases_blocked_read(self):
        raw = BlockingSource()
        task = asyncio.create_task(prepare_opus_source(raw))
        try:
            started = await asyncio.to_thread(raw.started.wait, 1)
            self.assertTrue(started)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(raw.cleaned)
        self.assertTrue(raw.released.is_set())

    def test_ffmpeg_outputs_twenty_millisecond_opus_pages(self):
        from util.music.source import ffmpeg_options

        self.assertIn("-frame_duration 20", ffmpeg_options["options"])
        self.assertIn("-page_duration 20000", ffmpeg_options["options"])
