from __future__ import annotations

import json
import io
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import discord
from PIL import Image

from cogs.earthquake_alert import EarthquakeAlertCommands
from util.earthquake.alerts import (
    EARTHQUAKE_ALERT_CHANNEL_TYPE,
    build_jma_eew_embed,
    edit_jma_eew_alert,
    process_jma_eew_event,
    send_jma_eew_alert,
)
from util.earthquake.jma_eew import (
    JmaEewEvent,
    is_recent_jma_eew,
    parse_jma_eew_message,
)
from util.earthquake.map_image import (
    EARTHQUAKE_MAP_FILENAME,
    EARTHQUAKE_MAP_HEIGHT,
    EARTHQUAKE_MAP_WIDTH,
    build_jma_eew_map_file,
)
from util.earthquake.state import (
    EarthquakeAlertState,
    find_jma_eew_record,
    remember_jma_eew_message,
)
from util.earthquake.stream import consume_jma_eew_messages
from util.earthquake.translation import (
    _extract_google_translation,
    translate_jma_eew_terms,
)


CHANNEL_SETTINGS_PATH = Path("cogs/channel_settings/__init__.py")
EARTHQUAKE_COG_PATH = Path("cogs/earthquake_alert/__init__.py")
HELP_PATH = Path("cogs/custom_help/__init__.py")
LOOP_PATH = Path("cogs/loop/__init__.py")
README_PATH = Path("README.md")
AGENTS_PATH = Path("AGENTS.md")
NOW = datetime.now(timezone.utc)


def _payload(
    *,
    event_id: str = "20260728165922",
    serial: int = 1,
    magnitude: float = 4.3,
    is_final: bool = False,
    is_cancelled: bool = False,
    is_training: bool = False,
) -> dict:
    announced = NOW.astimezone(timezone(timedelta(hours=9)))
    origin = announced - timedelta(seconds=15)
    return {
        "type": "jma_eew",
        "Title": "緊急地震速報（予報）",
        "CodeType": "緊急地震速報",
        "Issue": {"Source": "大阪", "Status": "通常"},
        "EventID": event_id,
        "Serial": serial,
        "AnnouncedTime": announced.strftime("%Y/%m/%d %H:%M:%S"),
        "OriginTime": origin.strftime("%Y/%m/%d %H:%M:%S"),
        "Hypocenter": "熊本県熊本地方",
        "Latitude": 32.7,
        "Longitude": 130.7,
        "Magunitude": magnitude,
        "Depth": 10,
        "MaxIntensity": "4",
        "WarnArea": [
            {
                "Chiiki": "熊本県熊本",
                "Shindo1": "4",
                "Shindo2": "4",
                "Type": "予報",
                "Arrive": "既に到達と予測",
            }
        ],
        "isSea": False,
        "isTraining": is_training,
        "isAssumption": False,
        "isWarn": False,
        "isFinal": is_final,
        "isCancel": is_cancelled,
    }


def _event(**overrides) -> JmaEewEvent:
    payload = _payload(**overrides)
    event = parse_jma_eew_message(payload)
    assert event is not None
    return event


class JmaEewParserTests(unittest.TestCase):
    def test_parses_wolfx_jma_eew_payload(self):
        event = _event(serial=8, magnitude=4.3, is_final=True)

        self.assertEqual(event.event_id, "20260728165922")
        self.assertEqual(event.serial, 8)
        self.assertEqual(event.magnitude, 4.3)
        self.assertEqual(event.hypocenter, "熊本県熊本地方")
        self.assertTrue(event.is_final)
        self.assertEqual(event.warn_areas[0].maximum_intensity, "4")

    def test_ignores_heartbeat_payload(self):
        self.assertIsNone(
            parse_jma_eew_message(
                {"type": "heartbeat", "timestamp": 1785225687453}
            )
        )

    def test_detects_stale_initial_snapshot(self):
        event = _event()
        self.assertTrue(is_recent_jma_eew(event, now=NOW))
        self.assertFalse(
            is_recent_jma_eew(
                event,
                now=NOW + timedelta(minutes=3),
            )
        )

    def test_channel_setting_and_stream_are_connected(self):
        channel_source = CHANNEL_SETTINGS_PATH.read_text(encoding="utf-8")
        loop_source = LOOP_PATH.read_text(encoding="utf-8")

        self.assertIn(
            '"earthquake_alert": "일본지진알림"',
            channel_source,
        )
        self.assertIn(
            'name="일본지진알림"',
            channel_source,
        )
        self.assertIn('"jma_eew_stream"', loop_source)
        self.assertIn("run_jma_eew_stream(self.bot)", loop_source)

    def test_exposes_alert_command_and_documents_delivery_pair(self):
        cog_source = EARTHQUAKE_COG_PATH.read_text(encoding="utf-8")
        help_source = HELP_PATH.read_text(encoding="utf-8")
        readme_source = README_PATH.read_text(encoding="utf-8")
        agents_source = AGENTS_PATH.read_text(encoding="utf-8")

        self.assertIn('name="지진알림"', cog_source)
        self.assertIn('status="true면 현재 채널로 알림을 받고', cog_source)
        self.assertIn("/지진알림", help_source)
        self.assertIn("/지진알림", readme_source)
        self.assertIn("@everyone", help_source)
        self.assertIn("@everyone", readme_source)
        self.assertIn("Notification Delivery Pairing", agents_source)
        self.assertIn("same `channel_type` key", agents_source)


class EarthquakeStateTests(unittest.TestCase):
    def test_remembers_latest_serial_and_message(self):
        state = EarthquakeAlertState(channel_id=100)
        state = remember_jma_eew_message(
            state,
            event_id="event-1",
            serial=1,
            message_id=900,
            everyone_notified=True,
        )
        state = remember_jma_eew_message(
            state,
            event_id="event-1",
            serial=2,
            message_id=900,
        )

        record = find_jma_eew_record(state, "event-1")
        self.assertIsNotNone(record)
        self.assertEqual(record.serial, 2)
        self.assertEqual(record.message_id, 900)
        self.assertTrue(record.everyone_notified)
        self.assertEqual(len(state.records), 1)


class EarthquakeAlertCommandTests(unittest.IsolatedAsyncioTestCase):
    def _interaction(self, *, channel_id: int | None = 456):
        return SimpleNamespace(
            guild_id=123,
            channel_id=channel_id,
            response=SimpleNamespace(
                defer=AsyncMock(),
                send_message=AsyncMock(),
            ),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_enable_uses_current_channel_and_resets_state(self):
        interaction = self._interaction()
        cog = EarthquakeAlertCommands(SimpleNamespace())

        with patch.object(
            cog,
            "_require_guild_admin",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "cogs.earthquake_alert.set_channel",
                new=AsyncMock(),
            ) as set_channel:
                with patch(
                    "cogs.earthquake_alert.delete_earthquake_alert_state",
                    new=AsyncMock(),
                ) as delete_state:
                    await cog.configure_earthquake_alert.callback(
                        cog,
                        interaction,
                        True,
                    )

        set_channel.assert_awaited_once_with(
            123,
            EARTHQUAKE_ALERT_CHANNEL_TYPE,
            456,
        )
        delete_state.assert_awaited_once_with(123)
        interaction.response.defer.assert_awaited_once_with(
            ephemeral=True,
            thinking=True,
        )
        self.assertIn(
            "알림 채널: <#456>",
            interaction.followup.send.await_args.args[0],
        )

    async def test_disable_clears_channel_and_state(self):
        interaction = self._interaction()
        cog = EarthquakeAlertCommands(SimpleNamespace())

        with patch.object(
            cog,
            "_require_guild_admin",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "cogs.earthquake_alert.set_channel",
                new=AsyncMock(),
            ) as set_channel:
                with patch(
                    "cogs.earthquake_alert.delete_earthquake_alert_state",
                    new=AsyncMock(),
                ) as delete_state:
                    await cog.configure_earthquake_alert.callback(
                        cog,
                        interaction,
                        False,
                    )

        set_channel.assert_awaited_once_with(
            123,
            EARTHQUAKE_ALERT_CHANNEL_TYPE,
            None,
        )
        delete_state.assert_awaited_once_with(123)
        self.assertIn(
            "알림을 해제했습니다",
            interaction.response.send_message.await_args.args[0],
        )


class JmaEewAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_first_magnitude_five_point_five_report(self):
        event = _event(magnitude=5.5)
        saved_states = []
        sent_events = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return EarthquakeAlertState(channel_id=100)

        async def save(_guild_id, state):
            saved_states.append(state)

        async def resolve(_bot, _channel_id):
            return object()

        async def send(_target, sent_event, notify_everyone):
            sent_events.append(sent_event)
            self.assertFalse(notify_everyone)
            return 900

        results = await process_jma_eew_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            save_state=save,
            resolve_channel=resolve,
            send_alert=send,
        )

        self.assertEqual(results[0].action, "sent")
        self.assertEqual(sent_events, [event])
        self.assertEqual(
            find_jma_eew_record(saved_states[0], event.event_id).message_id,
            900,
        )

    async def test_skips_first_report_below_magnitude_five_point_five(self):
        event = _event(magnitude=5.4)

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return EarthquakeAlertState(channel_id=100)

        async def send(_target, _event, _notify_everyone):
            raise AssertionError("M5.5 미만은 보내면 안 됩니다.")

        results = await process_jma_eew_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            send_alert=send,
        )

        self.assertEqual(results[0].status, "skipped")
        self.assertEqual(results[0].action, "below_threshold")

    async def test_edits_existing_message_for_later_report(self):
        event = _event(serial=2, magnitude=4.5, is_final=True)
        initial_state = remember_jma_eew_message(
            EarthquakeAlertState(channel_id=100),
            event_id=event.event_id,
            serial=1,
            message_id=900,
        )
        edited = []
        saved_states = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return initial_state

        async def save(_guild_id, state):
            saved_states.append(state)

        async def resolve(_bot, _channel_id):
            return object()

        async def edit(
            _target,
            message_id,
            edited_event,
            notify_everyone,
        ):
            edited.append((message_id, edited_event, notify_everyone))
            return message_id

        results = await process_jma_eew_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            save_state=save,
            resolve_channel=resolve,
            edit_alert=edit,
        )

        self.assertEqual(results[0].action, "edited")
        self.assertEqual(edited, [(900, event, False)])
        self.assertEqual(
            find_jma_eew_record(saved_states[0], event.event_id).serial,
            2,
        )

    async def test_cancel_report_edits_tracked_message(self):
        event = _event(serial=3, magnitude=0.0, is_cancelled=True)
        initial_state = remember_jma_eew_message(
            EarthquakeAlertState(channel_id=100),
            event_id=event.event_id,
            serial=2,
            message_id=900,
        )

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return initial_state

        async def save(_guild_id, _state):
            return None

        async def resolve(_bot, _channel_id):
            return object()

        async def edit(
            _target,
            message_id,
            _event,
            _notify_everyone,
        ):
            return message_id

        results = await process_jma_eew_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            save_state=save,
            resolve_channel=resolve,
            edit_alert=edit,
        )

        self.assertEqual(results[0].action, "cancelled")

    async def test_magnitude_seven_notifies_everyone_once(self):
        event = _event(magnitude=7.0)
        saved_states = []
        notifications = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return EarthquakeAlertState(channel_id=100)

        async def save(_guild_id, state):
            saved_states.append(state)

        async def resolve(_bot, _channel_id):
            return object()

        async def send(_target, _event, notify_everyone):
            notifications.append(notify_everyone)
            return 900

        await process_jma_eew_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            save_state=save,
            resolve_channel=resolve,
            send_alert=send,
        )

        self.assertEqual(notifications, [True])
        record = find_jma_eew_record(saved_states[0], event.event_id)
        self.assertTrue(record.everyone_notified)

    async def test_followup_crossing_magnitude_seven_notifies_once(self):
        event = _event(serial=2, magnitude=7.0)
        initial_state = remember_jma_eew_message(
            EarthquakeAlertState(channel_id=100),
            event_id=event.event_id,
            serial=1,
            message_id=900,
        )
        saved_states = []
        notifications = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return initial_state

        async def save(_guild_id, state):
            saved_states.append(state)

        async def resolve(_bot, _channel_id):
            return object()

        async def edit(
            _target,
            _message_id,
            _event,
            notify_everyone,
        ):
            notifications.append(notify_everyone)
            return 901

        await process_jma_eew_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            save_state=save,
            resolve_channel=resolve,
            edit_alert=edit,
        )

        self.assertEqual(notifications, [True])
        record = find_jma_eew_record(saved_states[0], event.event_id)
        self.assertEqual(record.message_id, 901)
        self.assertTrue(record.everyone_notified)

    async def test_later_magnitude_seven_followup_does_not_renotify(self):
        event = _event(serial=3, magnitude=7.1)
        initial_state = remember_jma_eew_message(
            EarthquakeAlertState(channel_id=100),
            event_id=event.event_id,
            serial=2,
            message_id=900,
            everyone_notified=True,
        )
        saved_states = []
        notifications = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return initial_state

        async def save(_guild_id, state):
            saved_states.append(state)

        async def resolve(_bot, _channel_id):
            return object()

        async def edit(
            _target,
            _message_id,
            _event,
            notify_everyone,
        ):
            notifications.append(notify_everyone)
            return 900

        await process_jma_eew_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            save_state=save,
            resolve_channel=resolve,
            edit_alert=edit,
        )

        self.assertEqual(notifications, [False])
        record = find_jma_eew_record(saved_states[0], event.event_id)
        self.assertTrue(record.everyone_notified)

    def test_builds_eew_embed(self):
        embed = build_jma_eew_embed(
            _event(serial=8, magnitude=4.3, is_final=True)
        )

        self.assertIn("M4.3", embed.title)
        self.assertEqual(
            [field.name for field in embed.fields[:6]],
            [
                "규모",
                "깊이",
                "최대 예상 진도",
                "발표 단계",
                "발표 시각",
                "발생 추정",
            ],
        )
        self.assertTrue(all(field.inline for field in embed.fields[:6]))
        self.assertIn("제 8보", embed.fields[3].value)
        self.assertIn("최종보", embed.fields[3].value)
        self.assertTrue(
            any(field.name == "예상 지역" for field in embed.fields)
        )

    def test_embed_uses_readable_map_link_and_attachment(self):
        embed = build_jma_eew_embed(_event(), include_map=True)
        hypocenter_field = next(
            field for field in embed.fields if field.name == "추정 진원"
        )

        self.assertIn("지도에서 크게 보기", hypocenter_field.value)
        self.assertIn("openstreetmap.org", hypocenter_field.value)
        self.assertNotIn("32.7000, 130.7000", hypocenter_field.value)
        self.assertEqual(
            embed.image.url,
            f"attachment://{EARTHQUAKE_MAP_FILENAME}",
        )

    async def test_builds_map_attachment_with_epicenter_marker(self):
        tile = Image.new("RGB", (256, 256), "#dce8d5")
        tile_output = io.BytesIO()
        tile.save(tile_output, format="PNG")
        tile_bytes = tile_output.getvalue()

        async def load_tile(_zoom, _tile_x, _tile_y):
            return tile_bytes

        map_file = await build_jma_eew_map_file(
            _event(),
            load_tile=load_tile,
        )

        self.assertIsNotNone(map_file)
        self.assertEqual(map_file.filename, EARTHQUAKE_MAP_FILENAME)
        with Image.open(map_file.fp) as rendered:
            self.assertEqual(
                rendered.size,
                (EARTHQUAKE_MAP_WIDTH, EARTHQUAKE_MAP_HEIGHT),
            )
            center = rendered.convert("RGB").getpixel(
                (EARTHQUAKE_MAP_WIDTH // 2, EARTHQUAKE_MAP_HEIGHT // 2)
            )
            self.assertGreater(center[0], center[1])
        map_file.close()

    async def test_send_attaches_map_image(self):
        target = SimpleNamespace(
            send=AsyncMock(return_value=SimpleNamespace(id=900))
        )
        fake_map = discord.File(
            io.BytesIO(b"map"),
            filename=EARTHQUAKE_MAP_FILENAME,
        )

        with patch(
            "util.earthquake.alerts.build_jma_eew_map_file",
            new=AsyncMock(return_value=fake_map),
        ):
            with patch(
                "util.earthquake.alerts.translate_jma_eew_terms",
                new=AsyncMock(return_value={}),
            ):
                message_id = await send_jma_eew_alert(target, _event())

        self.assertEqual(message_id, 900)
        send_options = target.send.await_args.kwargs
        self.assertIs(send_options["file"], fake_map)
        self.assertNotIn("content", send_options)
        self.assertFalse(send_options["allowed_mentions"].everyone)
        self.assertEqual(
            send_options["embed"].image.url,
            f"attachment://{EARTHQUAKE_MAP_FILENAME}",
        )
        fake_map.close()

    async def test_send_mentions_everyone_for_magnitude_seven(self):
        target = SimpleNamespace(
            send=AsyncMock(return_value=SimpleNamespace(id=900))
        )

        with patch(
            "util.earthquake.alerts.build_jma_eew_map_file",
            new=AsyncMock(return_value=None),
        ):
            with patch(
                "util.earthquake.alerts.translate_jma_eew_terms",
                new=AsyncMock(return_value={}),
            ):
                message_id = await send_jma_eew_alert(
                    target,
                    _event(magnitude=7.0),
                )

        self.assertEqual(message_id, 900)
        send_options = target.send.await_args.kwargs
        self.assertEqual(send_options["content"], "@everyone")
        self.assertTrue(send_options["allowed_mentions"].everyone)
        self.assertFalse(send_options["allowed_mentions"].users)
        self.assertFalse(send_options["allowed_mentions"].roles)

    async def test_edit_replaces_map_image_for_followup_report(self):
        existing_map = SimpleNamespace(filename=EARTHQUAKE_MAP_FILENAME)
        message = SimpleNamespace(
            id=900,
            attachments=[existing_map],
            edit=AsyncMock(),
        )
        target = SimpleNamespace(
            fetch_message=AsyncMock(return_value=message)
        )
        updated_map = discord.File(
            io.BytesIO(b"updated-map"),
            filename=EARTHQUAKE_MAP_FILENAME,
        )

        with patch(
            "util.earthquake.alerts.build_jma_eew_map_file",
            new=AsyncMock(return_value=updated_map),
        ):
            with patch(
                "util.earthquake.alerts.translate_jma_eew_terms",
                new=AsyncMock(return_value={}),
            ):
                message_id = await edit_jma_eew_alert(
                    target,
                    900,
                    _event(serial=2),
                )

        self.assertEqual(message_id, 900)
        edit_options = message.edit.await_args.kwargs
        self.assertEqual(edit_options["attachments"], [updated_map])
        self.assertEqual(
            edit_options["embed"].image.url,
            f"attachment://{EARTHQUAKE_MAP_FILENAME}",
        )
        updated_map.close()

    async def test_edit_replaces_message_when_everyone_must_be_notified(self):
        message = SimpleNamespace(
            id=900,
            attachments=[],
            delete=AsyncMock(),
        )
        target = SimpleNamespace(
            fetch_message=AsyncMock(return_value=message),
            send=AsyncMock(return_value=SimpleNamespace(id=901)),
        )

        with patch(
            "util.earthquake.alerts.build_jma_eew_map_file",
            new=AsyncMock(return_value=None),
        ):
            with patch(
                "util.earthquake.alerts.translate_jma_eew_terms",
                new=AsyncMock(return_value={}),
            ):
                message_id = await edit_jma_eew_alert(
                    target,
                    900,
                    _event(serial=2, magnitude=7.0),
                    notify_everyone=True,
                )

        self.assertEqual(message_id, 901)
        message.delete.assert_awaited_once_with()
        send_options = target.send.await_args.kwargs
        self.assertEqual(send_options["content"], "@everyone")
        self.assertTrue(send_options["allowed_mentions"].everyone)

    async def test_translates_displayed_japanese_terms_in_one_batch(self):
        requested = []

        async def translate_texts(texts):
            requested.append(texts)
            return {
                "熊本県熊本地方": "구마모토현 구마모토 지방",
                "熊本県熊本": "구마모토현 구마모토",
                "既に到達と予測": "이미 도달했을 것으로 예상",
            }

        event = _event()
        translated = await translate_jma_eew_terms(
            event,
            translate_texts=translate_texts,
        )
        embed = build_jma_eew_embed(
            event,
            translated_terms=translated,
        )
        expected_area_terms = (
            "熊本県熊本地方",
            "熊本県熊本",
            "既に到達と予測",
        )

        self.assertEqual(requested, [expected_area_terms])
        self.assertEqual(
            embed.description,
            "**熊本県熊本地方(구마모토현 구마모토 지방)**",
        )
        expected_area = next(
            field.value
            for field in embed.fields
            if field.name == "예상 지역"
        )
        self.assertIn(
            "熊本県熊本(구마모토현 구마모토)",
            expected_area,
        )
        self.assertIn(
            "既に到達と予測(이미 도달했을 것으로 예상)",
            expected_area,
        )

    def test_translation_failure_keeps_original_japanese_text(self):
        embed = build_jma_eew_embed(_event(), translated_terms={})

        self.assertEqual(embed.description, "**熊本県熊本地方**")

    def test_extracts_keyless_google_translation_segments(self):
        payload = [
            [
                ["구마모토현 ", "熊本県", None, None, 3],
                ["구마모토 지방", "熊本地方", None, None, 3],
            ],
            None,
            "ja",
        ]

        self.assertEqual(
            _extract_google_translation(payload),
            "구마모토현 구마모토 지방",
        )

    def test_embed_border_color_follows_magnitude_thresholds(self):
        cases = [
            (2.9, discord.Color.light_grey()),
            (3.0, discord.Color.green()),
            (4.0, discord.Color.yellow()),
            (5.0, discord.Color.orange()),
            (6.0, discord.Color.red()),
        ]

        for magnitude, expected_color in cases:
            with self.subTest(magnitude=magnitude):
                embed = build_jma_eew_embed(_event(magnitude=magnitude))
                self.assertEqual(embed.color, expected_color)

        cancelled = build_jma_eew_embed(
            _event(magnitude=6.0, is_cancelled=True)
        )
        self.assertEqual(cancelled.color, discord.Color.light_grey())


class JmaEewStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_consumes_heartbeat_and_eew_message(self):
        class FakeWebSocket:
            def __init__(self):
                self.sent = []
                self.messages = [
                    SimpleNamespace(
                        type=aiohttp.WSMsgType.TEXT,
                        data=json.dumps({"type": "heartbeat"}),
                    ),
                    SimpleNamespace(
                        type=aiohttp.WSMsgType.TEXT,
                        data=json.dumps(_payload(), ensure_ascii=False),
                    ),
                ]

            def __aiter__(self):
                self._iterator = iter(self.messages)
                return self

            async def __anext__(self):
                try:
                    return next(self._iterator)
                except StopIteration:
                    raise StopAsyncIteration

            async def send_str(self, value):
                self.sent.append(value)

        websocket = FakeWebSocket()
        processed_events = []

        async def process(_bot, event):
            processed_events.append(event)
            return []

        count = await consume_jma_eew_messages(
            object(),
            websocket,
            process_event=process,
        )

        self.assertEqual(count, 1)
        self.assertEqual(websocket.sent, ["ping"])
        self.assertEqual(processed_events[0].magnitude, 4.3)


if __name__ == "__main__":
    unittest.main()
