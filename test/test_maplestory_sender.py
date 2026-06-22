import unittest
import warnings

from util.maplestory.parser import MapleStoryEvent, MapleStoryNotice


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
    async def test_send_sunday_maple_event_to_channels_sends_embeds(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from util.maplestory_sender import send_sunday_maple_event_to_channels

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
            from util.maplestory_sender import send_sunday_maple_event_to_channels

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
            from util.maplestory_sender import send_maplestory_notice_to_channel

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
            from util.maplestory_sender import summarize_maplestory_notice_with_openai

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
            ["7/1까지 보상 수령 가능", "월드 내 1회 지급", "불필요한 인사말 제거"],
        )
        self.assertIn("정확히 3줄", calls[0][1])
        self.assertIn(notice.summary, calls[0][0])


class MapleStorySenderCompatibilityTests(unittest.TestCase):
    def test_legacy_maplestory_events_reexports_sender_entrypoints(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import util.maplestory_sender as maplestory_sender
            import util.maplestory_events as maplestory_events

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
