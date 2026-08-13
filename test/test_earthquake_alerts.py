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
from util.earthquake.emsc import (
    EMSC_KOREA_EVERYONE_MAGNITUDE,
    EMSC_KOREA_MIN_MAGNITUDE,
    EMSC_MIN_MAGNITUDE,
    EmscEvent,
    is_japan_emsc_event,
    is_korea_emsc_event,
    minimum_magnitude_for_emsc_event,
    parse_emsc_message,
)
from util.earthquake.emsc_alerts import (
    build_emsc_embed,
    edit_emsc_alert,
    process_emsc_event,
    send_emsc_alert,
)
from util.earthquake.emsc_stream import (
    _recover_emsc_updates,
    _should_log_reconnect_failure,
    consume_emsc_messages,
)
from util.earthquake.jma_eew import (
    JMA_EEW_MIN_MAGNITUDE,
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
    EmscAlertState,
    find_emsc_record,
    find_jma_eew_record,
    remember_emsc_message,
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


def _emsc_payload(
    *,
    event_id: str = "20260810_0000344",
    action: str = "create",
    magnitude: float = 6.5,
    region: str = "OFF COAST OF TARAPACA, CHILE",
    latitude: float = -18.63,
    longitude: float = -71.1,
    updated_offset_seconds: int = 0,
    event_type: str = "ke",
) -> dict:
    occurred_at = NOW - timedelta(seconds=30)
    updated_at = NOW + timedelta(seconds=updated_offset_seconds)
    return {
        "action": action,
        "data": {
            "type": "Feature",
            "id": event_id,
            "geometry": {
                "type": "Point",
                "coordinates": [longitude, latitude, -28.3],
            },
            "properties": {
                "source_id": "2040866",
                "source_catalog": "EMSC-RTS",
                "lastupdate": updated_at.isoformat().replace("+00:00", "Z"),
                "time": occurred_at.isoformat().replace("+00:00", "Z"),
                "flynn_region": region,
                "lat": latitude,
                "lon": longitude,
                "depth": 28.3,
                "evtype": event_type,
                "auth": "CSN",
                "mag": magnitude,
                "magtype": "ml",
                "unid": event_id,
            },
        },
    }


def _emsc_event(**overrides) -> EmscEvent:
    event = parse_emsc_message(_emsc_payload(**overrides))
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
            '"earthquake_alert": "지진알림"',
            channel_source,
        )
        self.assertIn(
            'name="지진알림"',
            channel_source,
        )
        self.assertIn('"jma_eew_stream"', loop_source)
        self.assertIn("run_jma_eew_stream(self.bot)", loop_source)
        self.assertIn('"emsc_earthquake_stream"', loop_source)
        self.assertIn("run_emsc_stream(self.bot)", loop_source)

    def test_exposes_alert_command_and_documents_delivery_pair(self):
        cog_source = EARTHQUAKE_COG_PATH.read_text(encoding="utf-8")
        help_source = HELP_PATH.read_text(encoding="utf-8")
        loop_source = LOOP_PATH.read_text(encoding="utf-8")
        readme_source = README_PATH.read_text(encoding="utf-8")
        agents_source = AGENTS_PATH.read_text(encoding="utf-8")

        self.assertIn('name="지진알림"', cog_source)
        self.assertIn('status="true면 현재 채널로 알림을 받고', cog_source)
        self.assertIn("/지진알림", help_source)
        self.assertIn("/지진알림", readme_source)
        self.assertIn("@everyone", help_source)
        self.assertIn("@everyone", readme_source)
        self.assertIn("EMSC", cog_source)
        self.assertIn("EMSC", help_source)
        self.assertIn("EMSC", readme_source)
        self.assertNotIn("일본지진알림", help_source)
        self.assertNotIn("일본지진알림", readme_source)
        for source in (cog_source, help_source, loop_source, readme_source):
            self.assertIn("M5.9", source)
            self.assertIn("M5.0", source)
            self.assertIn("M6.5", source)
        self.assertIn("한국 M5.5 이상은 @everyone", help_source)
        self.assertIn("한국 M5.5 이상은 사건당 한 번 @everyone", cog_source)
        self.assertIn("| 한국 및 한반도 인접 해역 | EMSC/CSEM | M5.0 이상 | M5.5 이상 |", readme_source)
        self.assertIn("그 밖의 국가에서 발생한 EMSC 지진은 규모와 관계없이 멘션하지 않습니다", readme_source)
        self.assertIn("Notification Delivery Pairing", agents_source)
        self.assertIn("same `channel_type` key", agents_source)


class EmscParserTests(unittest.TestCase):
    def test_parses_emsc_standing_order_payload(self):
        event = _emsc_event(magnitude=6.1)

        self.assertEqual(event.event_id, "20260810_0000344")
        self.assertEqual(event.magnitude, 6.1)
        self.assertEqual(event.depth_km, 28.3)
        self.assertEqual(event.region, "OFF COAST OF TARAPACA, CHILE")
        self.assertEqual(event.authority, "CSN")
        self.assertEqual(event.event_type, "ke")
        self.assertFalse(event.is_deleted)

    def test_uses_higher_send_threshold_than_jma(self):
        self.assertEqual(JMA_EEW_MIN_MAGNITUDE, 5.9)
        self.assertEqual(EMSC_KOREA_MIN_MAGNITUDE, 5.0)
        self.assertEqual(EMSC_KOREA_EVERYONE_MAGNITUDE, 5.5)
        self.assertEqual(EMSC_MIN_MAGNITUDE, 6.5)

    def test_detects_japan_region_for_duplicate_prevention(self):
        event = _emsc_event(
            region="NEAR EAST COAST OF HONSHU, JAPAN",
        )

        self.assertTrue(is_japan_emsc_event(event))

    def test_detects_korea_by_region_and_coordinates(self):
        region_event = _emsc_event(region="SOUTH KOREA")
        coordinate_event = _emsc_event(
            region="YELLOW SEA",
            latitude=35.5,
            longitude=125.8,
        )

        self.assertTrue(is_korea_emsc_event(region_event))
        self.assertTrue(is_korea_emsc_event(coordinate_event))
        self.assertEqual(
            minimum_magnitude_for_emsc_event(region_event),
            5.0,
        )
        self.assertEqual(
            minimum_magnitude_for_emsc_event(_emsc_event()),
            6.5,
        )

    def test_marks_delete_action(self):
        event = _emsc_event(action="delete")

        self.assertTrue(event.is_deleted)


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

    def test_remembers_latest_emsc_revision_and_message(self):
        state = EmscAlertState(channel_id=100)
        state = remember_emsc_message(
            state,
            event_id="event-1",
            revision="2026-08-10T10:00:00+00:00",
            message_id=900,
            everyone_notified=True,
        )
        state = remember_emsc_message(
            state,
            event_id="event-1",
            revision="2026-08-10T10:01:00+00:00",
            message_id=901,
        )

        record = find_emsc_record(state, "event-1")
        self.assertIsNotNone(record)
        self.assertEqual(record.revision, "2026-08-10T10:01:00+00:00")
        self.assertEqual(record.message_id, 901)
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
    async def test_sends_first_magnitude_five_point_nine_report(self):
        event = _event(magnitude=5.9)
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

    async def test_skips_first_report_below_magnitude_five_point_nine(self):
        event = _event(magnitude=5.8)

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return EarthquakeAlertState(channel_id=100)

        async def send(_target, _event, _notify_everyone):
            raise AssertionError("M5.9 미만은 보내면 안 됩니다.")

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


class EmscAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_first_korea_magnitude_five_event(self):
        event = _emsc_event(
            magnitude=5.0,
            region="SOUTH KOREA",
        )
        sent_events = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return EmscAlertState(channel_id=100)

        async def save(_guild_id, _state):
            return None

        async def resolve(_bot, _channel_id):
            return object()

        async def send(_target, sent_event, notify_everyone):
            sent_events.append(sent_event)
            self.assertFalse(notify_everyone)
            return 900

        results = await process_emsc_event(
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

    async def test_skips_first_korea_event_below_magnitude_five(self):
        event = _emsc_event(
            magnitude=4.9,
            region="SOUTH KOREA",
        )

        async def get_channels():
            return {1: 100}

        async def send(_target, _event, _notify_everyone):
            raise AssertionError("한국 EMSC M5.0 미만은 보내면 안 됩니다.")

        results = await process_emsc_event(
            object(),
            event,
            get_channels=get_channels,
            send_alert=send,
        )

        self.assertEqual(results[0].status, "skipped")
        self.assertEqual(results[0].action, "below_threshold")

    async def test_sends_first_magnitude_six_point_five_event(self):
        event = _emsc_event(magnitude=6.5)
        saved_states = []
        sent_events = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return EmscAlertState(channel_id=100)

        async def save(_guild_id, state):
            saved_states.append(state)

        async def resolve(_bot, _channel_id):
            return object()

        async def send(_target, sent_event, notify_everyone):
            sent_events.append(sent_event)
            self.assertFalse(notify_everyone)
            return 900

        results = await process_emsc_event(
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
            find_emsc_record(saved_states[0], event.event_id).message_id,
            900,
        )

    async def test_skips_first_event_below_magnitude_six_point_five(self):
        event = _emsc_event(magnitude=6.4)

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return EmscAlertState(channel_id=100)

        async def send(_target, _event, _notify_everyone):
            raise AssertionError("EMSC M6.5 미만은 보내면 안 됩니다.")

        results = await process_emsc_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            send_alert=send,
        )

        self.assertEqual(results[0].status, "skipped")
        self.assertEqual(results[0].action, "below_threshold")

    async def test_skips_japan_event_to_avoid_jma_duplicate(self):
        event = _emsc_event(region="HOKKAIDO, JAPAN REGION")

        async def get_channels():
            return {1: 100}

        results = await process_emsc_event(
            object(),
            event,
            get_channels=get_channels,
        )

        self.assertEqual(results[0].status, "skipped")
        self.assertEqual(results[0].action, "japan_duplicate")

    async def test_edits_tracked_event_when_emsc_updates_it(self):
        first_event = _emsc_event(magnitude=6.6)
        event = _emsc_event(
            action="update",
            magnitude=6.3,
            updated_offset_seconds=60,
        )
        initial_state = remember_emsc_message(
            EmscAlertState(channel_id=100),
            event_id=first_event.event_id,
            revision=first_event.revision,
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

        results = await process_emsc_event(
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
            find_emsc_record(saved_states[0], event.event_id).revision,
            event.revision,
        )

    async def test_delete_edits_tracked_message(self):
        first_event = _emsc_event(magnitude=6.5)
        event = _emsc_event(
            action="delete",
            magnitude=6.5,
            updated_offset_seconds=60,
        )
        initial_state = remember_emsc_message(
            EmscAlertState(channel_id=100),
            event_id=first_event.event_id,
            revision=first_event.revision,
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

        results = await process_emsc_event(
            object(),
            event,
            get_channels=get_channels,
            load_state=load,
            save_state=save,
            resolve_channel=resolve,
            edit_alert=edit,
        )

        self.assertEqual(results[0].action, "cancelled")

    async def test_korea_magnitude_five_point_five_notifies_once(self):
        state = EmscAlertState(channel_id=100)
        notifications = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return state

        async def save(_guild_id, updated_state):
            nonlocal state
            state = updated_state

        async def resolve(_bot, _channel_id):
            return object()

        async def send(_target, _event, notify_everyone):
            notifications.append(notify_everyone)
            return 900

        async def edit(
            _target,
            message_id,
            _event,
            notify_everyone,
        ):
            notifications.append(notify_everyone)
            return message_id

        for event in (
            _emsc_event(magnitude=5.0, region="SOUTH KOREA"),
            _emsc_event(
                action="update",
                magnitude=5.5,
                region="SOUTH KOREA",
                updated_offset_seconds=60,
            ),
            _emsc_event(
                action="update",
                magnitude=5.6,
                region="SOUTH KOREA",
                updated_offset_seconds=120,
            ),
        ):
            await process_emsc_event(
                object(),
                event,
                get_channels=get_channels,
                load_state=load,
                save_state=save,
                resolve_channel=resolve,
                send_alert=send,
                edit_alert=edit,
            )

        self.assertEqual(notifications, [False, True, False])
        record = find_emsc_record(state, "20260810_0000344")
        self.assertTrue(record.everyone_notified)

    async def test_non_korea_magnitude_seven_never_notifies_everyone(self):
        state = EmscAlertState(channel_id=100)
        notifications = []

        async def get_channels():
            return {1: 100}

        async def load(_guild_id):
            return state

        async def save(_guild_id, updated_state):
            nonlocal state
            state = updated_state

        async def resolve(_bot, _channel_id):
            return object()

        async def send(_target, _event, notify_everyone):
            notifications.append(notify_everyone)
            return 900

        async def edit(
            _target,
            message_id,
            _event,
            notify_everyone,
        ):
            notifications.append(notify_everyone)
            return message_id

        for event in (
            _emsc_event(magnitude=6.5),
            _emsc_event(
                action="update",
                magnitude=7.0,
                updated_offset_seconds=60,
            ),
            _emsc_event(
                action="update",
                magnitude=7.1,
                updated_offset_seconds=120,
            ),
        ):
            await process_emsc_event(
                object(),
                event,
                get_channels=get_channels,
                load_state=load,
                save_state=save,
                resolve_channel=resolve,
                send_alert=send,
                edit_alert=edit,
            )

        self.assertEqual(notifications, [False, False, False])
        record = find_emsc_record(state, "20260810_0000344")
        self.assertFalse(record.everyone_notified)

    def test_embed_matches_jma_layout_and_color_style(self):
        embed = build_emsc_embed(
            _emsc_event(magnitude=6.0),
            include_map=True,
        )

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
        self.assertEqual(embed.fields[2].value, "제공 안 함")
        self.assertEqual(embed.color, discord.Color.red())
        self.assertEqual(
            embed.image.url,
            f"attachment://{EARTHQUAKE_MAP_FILENAME}",
        )
        self.assertIn("EMSC/CSEM", embed.footer.text)

    async def test_send_never_mentions_everyone_for_non_korea_emsc(self):
        target = SimpleNamespace(
            send=AsyncMock(return_value=SimpleNamespace(id=900))
        )

        with patch(
            "util.earthquake.emsc_alerts.build_earthquake_map_file",
            new=AsyncMock(return_value=None),
        ):
            message_id = await send_emsc_alert(
                target,
                _emsc_event(magnitude=7.5),
                notify_everyone=True,
            )

        self.assertEqual(message_id, 900)
        send_options = target.send.await_args.kwargs
        self.assertNotIn("content", send_options)
        self.assertFalse(send_options["allowed_mentions"].everyone)
        self.assertFalse(send_options["allowed_mentions"].users)
        self.assertFalse(send_options["allowed_mentions"].roles)

    async def test_send_mentions_everyone_for_korea_magnitude_five_point_five(self):
        target = SimpleNamespace(
            send=AsyncMock(return_value=SimpleNamespace(id=900))
        )

        with patch(
            "util.earthquake.emsc_alerts.build_earthquake_map_file",
            new=AsyncMock(return_value=None),
        ):
            message_id = await send_emsc_alert(
                target,
                _emsc_event(
                    magnitude=5.5,
                    region="SOUTH KOREA",
                ),
            )

        self.assertEqual(message_id, 900)
        send_options = target.send.await_args.kwargs
        self.assertEqual(send_options["content"], "@everyone")
        self.assertTrue(send_options["allowed_mentions"].everyone)
        self.assertFalse(send_options["allowed_mentions"].users)
        self.assertFalse(send_options["allowed_mentions"].roles)

    async def test_edit_non_korea_removes_any_existing_everyone_content(self):
        message = SimpleNamespace(
            id=900,
            attachments=[],
            edit=AsyncMock(),
        )
        target = SimpleNamespace(
            fetch_message=AsyncMock(return_value=message)
        )

        with patch(
            "util.earthquake.emsc_alerts.build_earthquake_map_file",
            new=AsyncMock(return_value=None),
        ):
            message_id = await edit_emsc_alert(
                target,
                900,
                _emsc_event(action="update", magnitude=7.5),
                notify_everyone=True,
            )

        self.assertEqual(message_id, 900)
        edit_options = message.edit.await_args.kwargs
        self.assertIsNone(edit_options["content"])
        self.assertFalse(edit_options["allowed_mentions"].everyone)

    async def test_edit_replaces_korea_message_when_threshold_is_crossed(self):
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
            "util.earthquake.emsc_alerts.build_earthquake_map_file",
            new=AsyncMock(return_value=None),
        ):
            message_id = await edit_emsc_alert(
                target,
                900,
                _emsc_event(
                    action="update",
                    magnitude=5.5,
                    region="SOUTH KOREA",
                ),
                notify_everyone=True,
            )

        self.assertEqual(message_id, 901)
        message.delete.assert_awaited_once_with()
        send_options = target.send.await_args.kwargs
        self.assertEqual(send_options["content"], "@everyone")
        self.assertTrue(send_options["allowed_mentions"].everyone)


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


class EmscStreamTests(unittest.IsolatedAsyncioTestCase):
    def test_throttles_repeated_connection_failure_logs(self):
        logged_failures = {
            count
            for count in range(1, 22)
            if _should_log_reconnect_failure(count)
        }

        self.assertEqual(logged_failures, {1, 10, 20})

    async def test_consumes_emsc_standing_order_message(self):
        class FakeWebSocket:
            def __init__(self):
                self.messages = [
                    SimpleNamespace(
                        type=aiohttp.WSMsgType.TEXT,
                        data=json.dumps(
                            _emsc_payload(),
                            ensure_ascii=False,
                        ),
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

        processed_events = []

        async def process(_bot, event):
            processed_events.append(event)
            return []

        count = await consume_emsc_messages(
            object(),
            FakeWebSocket(),
            process_event=process,
        )

        self.assertEqual(count, 1)
        self.assertEqual(processed_events[0].event_id, "20260810_0000344")
        self.assertEqual(processed_events[0].magnitude, 6.5)

    async def test_recovers_recent_updates_after_reconnect(self):
        class FakeResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            async def json(self):
                return {
                    "type": "FeatureCollection",
                    "features": [_emsc_payload()["data"]],
                }

        class FakeSession:
            def __init__(self):
                self.url = None
                self.params = None

            def get(self, url, *, params):
                self.url = url
                self.params = params
                return FakeResponse()

        session = FakeSession()
        processed_events = []

        async def process(_bot, event):
            processed_events.append(event)
            return []

        count = await _recover_emsc_updates(
            object(),
            session,
            process_event=process,
            log=lambda _message: None,
            now=NOW,
        )

        self.assertEqual(count, 1)
        self.assertEqual(session.params["minmag"], "5.0")
        self.assertIn("updatedafter", session.params)
        self.assertEqual(processed_events[0].action, "update")

    async def test_empty_reconnect_backfill_response_is_not_an_error(self):
        class FakeResponse:
            status = 204

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def raise_for_status(self):
                raise AssertionError("204 must be handled before raise_for_status")

            async def json(self):
                raise AssertionError("204 must not be decoded as JSON")

        class FakeSession:
            def get(self, _url, *, params):
                self.params = params
                return FakeResponse()

        processed_events = []

        async def process(_bot, event):
            processed_events.append(event)
            return []

        count = await _recover_emsc_updates(
            object(),
            FakeSession(),
            process_event=process,
            log=lambda _message: None,
            now=NOW,
        )

        self.assertEqual(count, 0)
        self.assertEqual(processed_events, [])


if __name__ == "__main__":
    unittest.main()
