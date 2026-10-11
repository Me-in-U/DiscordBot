import asyncio
import json
import threading
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch


class RuntimeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_emsc_backfill_reads_every_page(self):
        from util.earthquake import emsc_stream as stream
        session=MagicMock()
        def response(features):
            value=MagicMock();value.status=200;value.json=AsyncMock(return_value={"features":features});value.__aenter__=AsyncMock(return_value=value)
            return value
        session.get.side_effect=[response([{}]*100),response([{}])]
        process=AsyncMock(return_value=[])
        with patch.object(stream,"parse_emsc_message",return_value=object()):
            count=await stream._recover_emsc_updates(object(),session,process_event=process,log=lambda _:None)
        self.assertEqual(count,101);self.assertEqual(process.await_count,101)
        self.assertEqual(session.get.call_count,2)
        self.assertEqual(session.get.call_args.kwargs["params"]["offset"],"101")

    async def test_emsc_failed_page_does_not_advance_saved_cursor(self):
        from util.earthquake import emsc_stream as stream
        session=MagicMock();session.get.side_effect=TimeoutError()
        read=AsyncMock(return_value={"setting_value":json.dumps("2026-10-10T00:00:00+00:00")});write=AsyncMock()
        with patch.object(stream,"fetch_one",read),patch.object(stream,"execute_query",write),self.assertLogs(stream.logger,level="WARNING"):
            await stream._recover_emsc_updates(object(),session,now=datetime(2026,10,11,tzinfo=timezone.utc))
        write.assert_not_awaited()
        self.assertIn("2026-10-09T23:59",session.get.call_args.kwargs["params"]["updatedafter"])

    def test_continuous_voice_is_flushed_at_five_seconds(self):
        from cogs.voice_chat import StreamingSink
        sink=StreamingSink(SimpleNamespace(bot=SimpleNamespace(loop=Mock())),SimpleNamespace(),"session")
        sink.SILENCE_THRESHOLD=1
        user=Mock();pcm=b"\x10\x00"*1920
        def flush(speaker): sink.user_buffers[speaker]=bytearray()
        with patch.object(sink,"_decode_voice_packet",return_value=pcm),patch.object(sink,"flush_user",side_effect=flush) as flushed:
            for _ in range(250): sink.write(user,object())
        flushed.assert_called_once_with(user)
        self.assertEqual(len(sink.user_buffers[user]),0)

    def test_saturated_voice_queue_drops_before_writing_file(self):
        from cogs.voice_chat import StreamingSink
        slots=threading.BoundedSemaphore(8)
        for _ in range(8): slots.acquire()
        sink=StreamingSink(SimpleNamespace(audio_slots=slots,bot=SimpleNamespace(loop=Mock())),SimpleNamespace(),"session")
        user=Mock();sink.user_buffers[user]=bytearray(192000);sink.user_pre_speech_buffer[user]=[]
        with patch("cogs.voice_chat.tempfile.NamedTemporaryFile") as create:
            sink.flush_user(user)
        create.assert_not_called();self.assertEqual(len(sink.user_buffers[user]),0)

    async def test_music_rejects_voice_receiver_before_listening_starts(self):
        from util.music.voice import ensure_music_voice_client
        result=await ensure_music_voice_client(voice_client=SimpleNamespace(listen=Mock(),is_listening=lambda:False),user_channel=object(),missing_channel_message="missing",busy_channel_message="busy")
        self.assertIsNotNone(result.error_message)

    async def test_pending_touch_keeps_newer_subscription_data(self):
        from util.youtube.notification_state import touch_pending_youtube_video_check
        from dataclasses import dataclass,field
        @dataclass
        class Subscription:
            id:int=1
            pending_videos:dict=field(default_factory=lambda:{"id":{"title":"new","scheduledStartTime":"2026-10-12T00:00:00Z"}})
            notified_video_ids:list=field(default_factory=list)
        updated=await touch_pending_youtube_video_check(Subscription(),"id",{"title":"old"},update_state=AsyncMock())
        self.assertEqual(updated.pending_videos["id"]["title"],"new")
        self.assertIn("firstSeenAt",updated.pending_videos["id"])

    async def test_weekly_retry_consumes_only_saved_snapshot(self):
        from util.loop import weekly_1557_reporter as weekly
        counts=AsyncMock(return_value=[{"user_id":1,"count":70}]);write=AsyncMock();send=AsyncMock()
        snapshot=json.dumps({"counts":{"1":50},"done":False})
        @asynccontextmanager
        async def transaction(): yield
        with patch.object(weekly,"fetch_weekly_1557_counts",counts),patch.object(weekly,"fetch_one",AsyncMock(return_value={"setting_value":snapshot})),patch.object(weekly,"execute_query",write),patch.object(weekly,"transaction",transaction),patch.object(weekly,"send_once",send):
            await weekly.run_weekly_1557_report(SimpleNamespace(get_channel=lambda _:object()),target_channel_id=1,now=datetime(2026,10,12),fetch_counts=counts,log=lambda _:None)
        update=next(call for call in write.await_args_list if "UPDATE counter_1557" in call.args[0])
        self.assertEqual(update.args[1],(50,1))
        self.assertIn("50",send.await_args.kwargs["content"])

    async def test_cancelled_summary_holds_slot_until_worker_finishes(self):
        from func import youtube_processor as processor
        started=asyncio.Event();finish=asyncio.Event()
        @processor.limited_summary
        async def work():
            started.set();await finish.wait();return "ok"
        with patch.object(processor,"_summary_slot",asyncio.Semaphore(1)):
            task=asyncio.create_task(work());await started.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertTrue(processor._summary_slot.locked())
            finish.set();await asyncio.sleep(0);await asyncio.sleep(0)
            self.assertFalse(processor._summary_slot.locked())

    async def test_readiness_requires_actual_loop_cog_and_running_tasks(self):
        from cogs.status_api import StatusApi
        from bot import REQUIRED_COGS
        from cogs.loop import LOOP_TASK_NAMES
        bot=SimpleNamespace(is_ready=lambda:True,startup_completed=True,extensions=REQUIRED_COGS,guilds=[],latency=0,user=None,get_cog=lambda _:None)
        owner=SimpleNamespace(bot=bot,start_time=0)
        with patch("cogs.status_api.ensure_schema_ready",AsyncMock()):
            self.assertEqual((await StatusApi.health_handler(owner,None)).status,503)
            loops=SimpleNamespace(**{name:SimpleNamespace(is_running=lambda:True) for name in LOOP_TASK_NAMES})
            bot.get_cog=lambda _:loops
            self.assertEqual((await StatusApi.health_handler(owner,None)).status,200)
            getattr(loops,LOOP_TASK_NAMES[0]).is_running=lambda:False
            self.assertEqual((await StatusApi.health_handler(owner,None)).status,503)

    async def test_earthquake_replacement_has_separate_delivery_key(self):
        import discord
        from util.earthquake import emsc_alerts as alerts
        event=SimpleNamespace(event_id="id",revision="revision")
        send=AsyncMock(return_value=SimpleNamespace(id=100))
        with patch.object(alerts,"send_once",send),patch.object(alerts,"build_earthquake_map_file",AsyncMock(return_value=None)),patch.object(alerts,"build_emsc_embed",return_value=discord.Embed(title="test")),patch.object(alerts,"_should_show_everyone",return_value=False):
            await alerts.send_emsc_alert(object(),event)
            await alerts.send_emsc_alert(object(),event,replacement_of=99)
        self.assertNotEqual(send.await_args_list[0].args[1],send.await_args_list[1].args[1])
