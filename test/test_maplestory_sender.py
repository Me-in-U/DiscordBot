import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from util.maplestory.parser import MapleStoryEvent, MapleStoryNotice


MAPLESTORY_SENDER_PATH = Path("util/maplestory/sender.py")
LEGACY_MAPLESTORY_SENDER_PATH = Path("util/maplestory_sender.py")


class FakeSentMessage:
    id = 2468


class FakeTextChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.sent_messages = []

    async def send(self, *args, **kwargs):
        self.sent_messages.append({"args": args, "kwargs": kwargs})
        return FakeSentMessage()


class MapleStorySenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_maplestory_sender_lives_under_maplestory_package(self):
        self.assertTrue(MAPLESTORY_SENDER_PATH.exists())
        self.assertFalse(LEGACY_MAPLESTORY_SENDER_PATH.exists())

    async def test_send_sunday_maple_event_to_channels_sends_embeds(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory.sender import send_sunday_maple_event_to_channels

        event = MapleStoryEvent(
            title="스페셜 썬데이 메이플",
            url="https://maplestory.nexon.com/News/Event/Ongoing/1350",
            period="2026년 06월 21일 00시 00분 ~ 2026년 06월 21일 23시 59분",
            image_urls=["https://example.com/body.png"],
        )
        channel = FakeTextChannel(channel_id=1234)

        results = await send_sunday_maple_event_to_channels({10: channel}, event)

        self.assertEqual(results[0].guild_id, 10)
        self.assertEqual(results[0].channel_id, 1234)
        self.assertEqual(results[0].message_id, 2468)
        self.assertEqual(results[0].action, "sent")
        self.assertEqual(channel.sent_messages[0]["kwargs"]["embeds"][0].image.url, event.image_urls[0])

    async def test_send_sunday_maple_event_to_channels_skips_missing_images(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory.sender import send_sunday_maple_event_to_channels

        channel = FakeTextChannel(channel_id=1234)
        results = await send_sunday_maple_event_to_channels(
            {10: channel},
            MapleStoryEvent(
                title="스페셜 썬데이 메이플",
                url="https://maplestory.nexon.com/News/Event/Ongoing/1350",
            ),
        )

        self.assertEqual(results[0].action, "missing_images")
        self.assertEqual(results[0].status, "skipped")
        self.assertEqual(channel.sent_messages, [])

    async def test_send_maplestory_notice_to_channel_sends_three_line_embed(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory.sender import send_maplestory_notice_to_channel

        channel = FakeTextChannel(channel_id=1234)
        notice = MapleStoryNotice(
            notice_id="149371",
            category="[점검]",
            title="6/22(월) 서버 점검",
            url="https://maplestory.nexon.com/News/Notice/149371",
            summary="점검이 완료되었습니다.",
        )

        async def fake_summarize_notice(input_notice):
            self.assertEqual(input_notice, notice)
            return [
                "전체 월드 채널 점검 완료",
                "오후 4시 30분부터 정상 이용",
                "접속 중이면 재접속 필요",
            ]

        result = await send_maplestory_notice_to_channel(
            channel,
            guild_id=10,
            channel_id=1234,
            notice=notice,
            summarize_notice=fake_summarize_notice,
        )

        self.assertEqual(result.action, "sent")
        self.assertEqual(result.notice_id, "149371")
        self.assertEqual(result.message_id, 2468)
        sent = channel.sent_messages[0]
        self.assertEqual(sent["args"], ())
        embed = sent["kwargs"]["embed"]
        self.assertEqual(embed.title, "6/22(월) 서버 점검")
        self.assertEqual(embed.url, "https://maplestory.nexon.com/News/Notice/149371")
        self.assertEqual(
            embed.description,
            "전체 월드 채널 점검 완료\n오후 4시 30분부터 정상 이용\n접속 중이면 재접속 필요",
        )

    async def test_openai_notice_summary_is_coerced_to_three_compact_lines(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory.sender import summarize_maplestory_notice_with_openai

        notice = MapleStoryNotice(
            notice_id="149372",
            category="[공지]",
            title="사과 보상 안내",
            url="https://maplestory.nexon.com/News/Notice/149372",
            summary="안녕하세요. 메이플스토리입니다. 불편 보상은 7/1까지 수령 가능합니다. 월드 내 1회만 받을 수 있습니다.",
        )

        calls = []

        def fake_generate_text_model(user_input, instructions, model, max_output_tokens):
            calls.append((user_input, instructions, model, max_output_tokens))
            return "1. 7/1까지 보상 수령 가능\n- 월드 내 1회 지급\n불필요한 인사말 제거\n네번째 줄 제거"

        lines = await summarize_maplestory_notice_with_openai(
            notice,
            generate_text=fake_generate_text_model,
        )

        self.assertEqual(
            lines,
            ["7/1까지 보상 수령 가능", "월드 내 1회 지급", "불필요한 인사말 제거", "네번째 줄 제거"],
        )
        self.assertIn("3~4줄", calls[0][1])
        self.assertNotIn("알아서", calls[0][1])
        self.assertNotIn("핵심은", calls[0][1])
        self.assertNotIn("헛걸음", calls[0][1])
        self.assertIn(notice.summary, calls[0][0])

    async def test_short_notice_summary_input_includes_full_body_text(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory.sender import _build_maplestory_notice_summary_input

        notice = MapleStoryNotice(
            notice_id="149380",
            category="[공지]",
            title="(수정) 6/25(목) 넥슨 정기점검 안내",
            url="https://maplestory.nexon.com/News/Notice/149380",
            summary="짧은 공지 요약",
            body_text=(
                "안녕하세요, 넥슨 고객 여러분. 매주 목요일은 넥슨 정기점검입니다. "
                "오전 3시 ~ 오전 8시 고객센터 이용 불가. 오전 7시 ~ 오전 8시 넥슨PC방 홈페이지 이용 불가."
            ),
        )

        summary_input = _build_maplestory_notice_summary_input(notice)

        self.assertIn("본문 발췌 방식: 전문", summary_input)
        self.assertIn("오전 3시 ~ 오전 8시 고객센터 이용 불가", summary_input)
        self.assertIn("오전 7시 ~ 오전 8시 넥슨PC방 홈페이지 이용 불가", summary_input)

    async def test_long_notice_summary_input_keeps_important_blocks(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory.sender import _build_maplestory_notice_summary_input

        long_intro = "안녕하세요. 용사님! " + "인사말입니다. " * 140
        body = (
            f"{long_intro}"
            "[작업 일시] 2026년 6월 23일 오후 5시 45분 ~ 오후 6시 45분 (1시간) "
            "[작업 대상] 모든 월드 1~29채널, 일부 월드 30~79채널은 구간별로 진행 "
            "[작업 내역] 서버 안정화 "
            "[관련 공지] 이 블록은 요약 입력에서 우선하지 않는다 "
            "[기타] 중요하지 않은 안내 " + "반복 안내 " * 200
        )
        notice = MapleStoryNotice(
            notice_id="149382",
            category="[점검]",
            title="[점검완료] 6/23(화) 전체 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149382",
            summary=body[:220],
            body_text=body,
        )

        summary_input = _build_maplestory_notice_summary_input(notice)

        self.assertIn("본문 발췌 방식: 중요 블록", summary_input)
        self.assertIn("[작업 일시] 2026년 6월 23일", summary_input)
        self.assertIn("[작업 대상] 모든 월드", summary_input)
        self.assertIn("[작업 내역] 서버 안정화", summary_input)
        self.assertNotIn("인사말입니다. 인사말입니다. 인사말입니다.", summary_input)
        self.assertLessEqual(len(summary_input), 2600)

    async def test_fallback_notice_summary_uses_spicy_three_or_four_lines(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory.sender import summarize_maplestory_notice_with_openai

        notice = MapleStoryNotice(
            notice_id="149382",
            category="[점검]",
            title="[점검완료] 6/23(화) 전체 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149382",
            summary="2026년 6월 23일 오후 5시 45분 ~ 오후 6시 45분 채널 점검입니다.",
            body_text=(
                "[작업 일시] 2026년 6월 23일 오후 5시 45분 ~ 오후 6시 45분 "
                "[작업 대상] 모든 메이플스토리 월드 "
                "[작업 내역] 서버 안정화"
            ),
        )

        def failing_generate_text_model(user_input, instructions, model, max_output_tokens):
            raise RuntimeError("boom")

        with patch("util.maplestory.sender.logger.warning"):
            lines = await summarize_maplestory_notice_with_openai(
                notice,
                generate_text=failing_generate_text_model,
            )

        self.assertGreaterEqual(len(lines), 3)
        self.assertLessEqual(len(lines), 4)
        self.assertTrue(any("점검" in line for line in lines))
        rendered = "\n".join(lines)
        self.assertNotIn("핵심은", rendered)
        self.assertNotIn("헛걸음", rendered)
        self.assertNotIn("자세한 건 원문 보고", rendered)

    def test_fallback_notice_summary_first_line_reflects_notice_status(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory.sender import _fallback_maplestory_notice_summary_lines

        scheduled = MapleStoryNotice(
            notice_id="149500",
            category="[점검]",
            title="[점검예정] 6/25(목) 챌린저스 월드 채널 점검 (11:50~12:50)",
            url="https://maplestory.nexon.com/News/Notice/149500",
            summary="2026년 6월 25일 오전 11시 50분 ~ 낮 12시 50분 채널 점검입니다.",
            body_text="[작업 일시] 2026년 6월 25일 오전 11시 50분 ~ 낮 12시 50분 [작업 대상] 챌린저스 월드",
        )
        in_progress = MapleStoryNotice(
            notice_id="149500",
            category="[점검]",
            title="[점검중] 6/25(목) 챌린저스 월드 채널 점검 (11:50~12:50)",
            url="https://maplestory.nexon.com/News/Notice/149500",
            summary=scheduled.summary,
            body_text=scheduled.body_text,
        )
        completed = MapleStoryNotice(
            notice_id="149500",
            category="[점검]",
            title="[점검완료] 6/25(목) 챌린저스 월드 채널 점검 (11:50~12:50)",
            url="https://maplestory.nexon.com/News/Notice/149500",
            summary=scheduled.summary,
            body_text=scheduled.body_text,
        )

        first_lines = {
            _fallback_maplestory_notice_summary_lines(scheduled)[0],
            _fallback_maplestory_notice_summary_lines(in_progress)[0],
            _fallback_maplestory_notice_summary_lines(completed)[0],
        }

        self.assertEqual(len(first_lines), 3)
        self.assertTrue(any("예정" in line for line in first_lines))
        self.assertTrue(any("진행" in line for line in first_lines))
        self.assertTrue(any("완료" in line for line in first_lines))


class MapleStorySenderCompatibilityTests(unittest.TestCase):
    def test_legacy_maplestory_events_reexports_sender_entrypoints(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import util.maplestory.sender as maplestory_sender
            import util.maplestory.events as maplestory_events

        self.assertIs(
            maplestory_events.SundayMapleUpdateResult,
            maplestory_sender.SundayMapleUpdateResult,
        )
        self.assertIs(
            maplestory_events.MapleStoryNoticeUpdateResult,
            maplestory_sender.MapleStoryNoticeUpdateResult,
        )
        self.assertIs(
            maplestory_events.build_sunday_maple_event_embeds,
            maplestory_sender.build_sunday_maple_event_embeds,
        )
        self.assertIs(
            maplestory_events.build_maplestory_notice_message,
            maplestory_sender.build_maplestory_notice_message,
        )
        self.assertIs(
            maplestory_events.build_maplestory_notice_embed,
            maplestory_sender.build_maplestory_notice_embed,
        )


if __name__ == "__main__":
    unittest.main()
