import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.channel_settings import ChannelSettings, PURPOSE_CHOICES
from cogs.disaster_sms import DisasterSmsCommands, fetch_notices
from util import disaster_sms


def notice(body, category="민방공", level="안전안내"):
    return {
        "MSG_CN": body,
        "DST_SE_NM": category,
        "EMRG_STEP_NM": level,
        "RCPTN_RGN_NM": "경상북도 울릉군",
        "CRT_DT": "2026/11/24 07:53:05",
        "SN": 270252,
    }


class DisasterSmsTests(unittest.IsolatedAsyncioTestCase):
    def test_nationwide_alert_categories_and_exclusions(self):
        cases = (
            (notice("07:52 러시아 항공기 접근, 울릉군지역 경계경보, 건물 내로 대피."), "alert"),
            (notice("07:55 울릉군지역 경보를 해제합니다."), "update"),
            (notice("앞서 발송된 문자를 정정합니다."), "update"),
            (notice("오늘 14:00 공습 대비 민방위 훈련으로 공습경보가 울립니다.", level="위급재난"), None),
            (notice("재난문자 시험 송출입니다. [테스트]", "기타", "위급재난"), None),
            (notice("위급재난문자입니다. 대학수학능력시험 진행 안내.", "기타", "위급재난"), None),
            (notice("규모 6.0 지진", "지진", "위급재난"), "alert"),
            (notice("지진해일경보 발령", "지진해일", "긴급재난"), "alert"),
            (notice("지진해일주의보 발령", "지진해일", "긴급재난"), None),
            (notice("산불 확산으로 주민 대피명령 발령", "산불", "긴급재난"), None),
            (notice("산불 확산으로 즉시 대피하세요.", "화재", "위급재난"), None),
            (notice("주민 대피명령 발령", "산불", "긴급재난"), None),
            (notice("화재 발생. 대피 준비 바랍니다.", "화재"), None),
            (notice("홍수로 인근 주민은 즉시 대피하세요.", "홍수", "긴급재난"), "alert"),
            (notice("홍수 수위가 높아질 예정이니 접근을 자제하세요.", "홍수", "긴급재난"), None),
        )
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(disaster_sms.classify_notice(row), expected)
        self.assertEqual(disaster_sms.notice_time(cases[0][0]).utcoffset(), timedelta(hours=9))

    def test_excludes_wildfire_followup_for_previous_alert(self):
        row = notice("주민 대피명령 해제", "산불", "긴급재난")
        self.assertIsNone(disaster_sms.classify_notice(row, related=True))

    async def test_delivers_alert_and_mutes_followups_without_replay(self):
        bot = MagicMock()
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild.id = 1
        channel.send = AsyncMock()
        bot.get_channel.return_value = channel
        cog = DisasterSmsCommands(bot)
        now = datetime.now(disaster_sms.KST)
        state = {
            "channel_id": 2,
            "since": (now - timedelta(minutes=5)).isoformat(),
            "serial": 0,
            "alerts": {},
        }
        rows = [
            (10, now - timedelta(minutes=6), notice("이전 경계경보")),
            (11, now, notice("울릉군지역 경계경보.")),
            (12, now, notice("경보 해제.")),
            (13, now, notice("발송 문자를 정정합니다.")),
            (14, now, notice("[훈련] 공습경보", level="위급재난")),
        ]
        with (
            patch.object(disaster_sms, "load_state", new=AsyncMock(return_value=state)),
            patch.object(disaster_sms, "save_state", new=AsyncMock()),
        ):
            await cog.deliver(1, 2, rows, now)
            await cog.deliver(1, 2, rows, now)

        deliveries = [call.kwargs for call in channel.send.await_args_list]
        self.assertEqual([call["content"] for call in deliveries], ["@everyone", None, None])
        self.assertEqual([call["allowed_mentions"].everyone for call in deliveries], [True, False, False])
        self.assertEqual(state["serial"], 14)

    async def test_fetches_single_page_without_a_region_filter(self):
        row = notice("경계경보 발령")
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={"header": {"resultCode": "00"}, "body": [row]})
        request = MagicMock()
        request.__aenter__.return_value = response
        session = MagicMock()
        session.get.return_value = request
        context = MagicMock()
        context.__aenter__.return_value = session
        with patch("cogs.disaster_sms.aiohttp.ClientSession", return_value=context):
            self.assertEqual(await fetch_notices("test-key"), [row])

        session.get.assert_called_once()
        self.assertNotIn("rgnNm", session.get.call_args.kwargs["params"])

    def test_channel_settings_and_dedicated_command_are_registered(self):
        choices = ChannelSettings.configure_channel.get_parameter("purpose").choices
        self.assertEqual(PURPOSE_CHOICES[disaster_sms.CHANNEL_TYPE], "재난문자")
        self.assertIn(disaster_sms.CHANNEL_TYPE, [choice.value for choice in choices])
        self.assertEqual(DisasterSmsCommands.configure_disaster_sms.name, "재난문자")
