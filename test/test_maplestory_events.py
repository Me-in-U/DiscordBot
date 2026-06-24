import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from util.maplestory.events import (
    MapleStoryEvent,
    MapleStoryNotice,
    SUNDAY_MAPLE_EVENT_TITLE,
    build_maplestory_notice_embed,
    build_maplestory_notice_message,
    build_sunday_maple_event_embeds,
    fetch_sunday_maple_event,
    find_maplestory_notice_updates,
    maplestory_notice_state_from_notices,
    parse_maplestory_notice_detail,
    parse_maplestory_notice_list,
    parse_maplestory_event_detail,
    parse_maplestory_ongoing_event_url,
    refresh_sunday_maple_messages,
)


MAPLESTORY_EVENTS_PATH = Path("util/maplestory/events.py")
LEGACY_MAPLESTORY_EVENTS_PATH = Path("util/maplestory_events.py")


LIST_HTML = """
<div class="event_list_wrap">
    <dl>
        <dt><a href="/News/Event/Ongoing/1350"><img src="thumb.png" alt="종료된 이벤트 섬네일" /></a></dt>
        <dd class="data">
            <p>
                <a href="/News/Event/Ongoing/1350">
                    <em class="event_listMt">
                        스페셜 썬데이 메이플
                    </em>
                </a>
            </p>
        </dd>
        <dd class="date"><p>2026.06.21 ~ 2026.06.21</p></dd>
    </dl>
</div>
"""

DETAIL_HTML = """
<p class="qs_title">
    <img src="title.png" alt="" />
    <span> 스페셜 썬데이 메이플</span>
</p>
<div class="qs_info_wrap">
    <span class="event_date">2026년 06월 21일 00시 00분  ~ 2026년 06월 21일 00시 00분</span>
</div>
<div class="qs_text">
    <div class="new_board_con">
        <body>
            <div class="gen_container">
                <img src="https://lwi.nexon.com/maplestory/2026/0621_board/21E9057CA56D8A9C.png" style="width: 100%; height: auto;">
            </div>
        </body>
    </div>
</div>
<div class="event_view_roll">
    <img src="https://file.nexon.com/NxFile/download/FileDownloader.aspx?oidFile=5557534578324800538" alt="스페셜 썬데이 메이플">
</div>
"""

NOTICE_LIST_HTML = """
<ul class="news_board">
    <li>
        <p>
            <a href="/News/Notice/All/149371">
                <em><img src="notice_icon03.png" alt="[점검]" /></em>
                <span>[패치완료] 6/22(월) ver1.2.416 마이너(6) 패치(16:55 적용)</span>
                <img class="new" alt="" src="new.png" />
            </a>
        </p>
    </li>
    <li>
        <p>
            <a href="/News/Notice/All/149370">
                <em><img src="notice_icon01.png" alt="[공지]" /></em>
                <span>6/22(월) 사과 보상 안내</span>
            </a>
        </p>
    </li>
</ul>
"""

NOTICE_DETAIL_HTML = """
<p class="qs_title" style="margin-top:30px">
    <em class="notice_icon"><img src="notice_icon01.png" alt="[공지]" /></em>
    <span>6/22(월) 사과 보상 안내</span>
</p>
<div class="qs_info_wrap">
    <div class="qs_info"><p class="last">PM 04:24</p></div>
</div>
<div class="qs_text">
    <div class="new_board_con">
        <p>안녕하세요. 메이플스토리 입니다.</p>
        <p>불편을 드려 죄송합니다. 7/1(수)까지 수령해 주세요.</p>
        <p>더 나은 서비스 제공을 위해 최선을 다하겠습니다.</p>
    </div>
</div>
<div class="page_move"></div>
"""


class MapleStoryEventTests(unittest.TestCase):
    def test_maplestory_events_lives_under_maplestory_package(self):
        self.assertTrue(MAPLESTORY_EVENTS_PATH.exists())
        self.assertFalse(LEGACY_MAPLESTORY_EVENTS_PATH.exists())

    def test_parses_sunday_maple_url_from_ongoing_event_list(self):
        event_url = parse_maplestory_ongoing_event_url(LIST_HTML)

        self.assertEqual(
            event_url,
            "https://maplestory.nexon.com/News/Event/Ongoing/1350",
        )

    def test_ongoing_event_list_returns_none_when_sunday_maple_is_absent(self):
        event_url = parse_maplestory_ongoing_event_url(
            LIST_HTML.replace(SUNDAY_MAPLE_EVENT_TITLE, "다른 이벤트")
        )

        self.assertIsNone(event_url)

    def test_extracts_only_body_images_from_event_detail(self):
        event = parse_maplestory_event_detail(
            DETAIL_HTML,
            event_url="https://maplestory.nexon.com/News/Event/Ongoing/1350",
        )

        self.assertEqual(event.title, SUNDAY_MAPLE_EVENT_TITLE)
        self.assertEqual(
            event.period,
            "2026년 06월 21일 00시 00분 ~ 2026년 06월 21일 00시 00분",
        )
        self.assertEqual(
            event.image_urls,
            [
                "https://lwi.nexon.com/maplestory/2026/0621_board/21E9057CA56D8A9C.png"
            ],
        )

    def test_fetch_sunday_maple_event_uses_list_then_detail_page(self):
        requested_urls = []

        async def fake_fetch(url: str) -> str:
            requested_urls.append(url)
            if url.endswith("/News/Event/Ongoing"):
                return LIST_HTML
            return DETAIL_HTML

        event = asyncio.run(fetch_sunday_maple_event(fetch_html=fake_fetch))

        self.assertEqual(
            requested_urls,
            [
                "https://maplestory.nexon.com/News/Event/Ongoing",
                "https://maplestory.nexon.com/News/Event/Ongoing/1350",
            ],
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.image_urls[0], "https://lwi.nexon.com/maplestory/2026/0621_board/21E9057CA56D8A9C.png")

    def test_fetch_sunday_maple_event_returns_none_when_event_is_absent(self):
        async def fake_fetch(url: str) -> str:
            return LIST_HTML.replace(SUNDAY_MAPLE_EVENT_TITLE, "다른 이벤트")

        self.assertIsNone(asyncio.run(fetch_sunday_maple_event(fetch_html=fake_fetch)))

    def test_builds_sunday_maple_embeds_for_event_images(self):
        event = MapleStoryEvent(
            title=SUNDAY_MAPLE_EVENT_TITLE,
            url="https://maplestory.nexon.com/News/Event/Ongoing/1350",
            period="2026년 06월 21일 00시 00분 ~ 2026년 06월 21일 00시 00분",
            image_urls=[
                "https://lwi.nexon.com/maplestory/2026/0621_board/21E9057CA56D8A9C.png"
            ],
        )

        embeds = build_sunday_maple_event_embeds(event)

        self.assertEqual(len(embeds), 1)
        self.assertEqual(embeds[0].title, SUNDAY_MAPLE_EVENT_TITLE)
        self.assertEqual(embeds[0].url, event.url)
        self.assertEqual(embeds[0].image.url, event.image_urls[0])

    def test_refresh_sunday_maple_messages_sends_to_celebration_channels(self):
        event = MapleStoryEvent(
            title=SUNDAY_MAPLE_EVENT_TITLE,
            url="https://maplestory.nexon.com/News/Event/Ongoing/1350",
            period="2026년 06월 21일 00시 00분 ~ 2026년 06월 21일 00시 00분",
            image_urls=[
                "https://lwi.nexon.com/maplestory/2026/0621_board/21E9057CA56D8A9C.png"
            ],
        )
        channel = _FakeTextChannel(channel_id=1234)

        async def fake_fetch_event():
            return event

        async def fake_get_channels(bot, guild_id=None):
            return {10: channel}

        with patch("util.celebration.announcements.get_celebration_channels", fake_get_channels):
            results = asyncio.run(
                refresh_sunday_maple_messages(
                    bot=object(),
                    fetch_event=fake_fetch_event,
                )
            )

        self.assertEqual(results[0].guild_id, 10)
        self.assertEqual(results[0].channel_id, 1234)
        self.assertEqual(results[0].action, "sent")
        self.assertEqual(results[0].status, "ok")
        self.assertEqual(len(channel.sent_messages), 1)
        self.assertEqual(channel.sent_messages[0]["embeds"][0].title, SUNDAY_MAPLE_EVENT_TITLE)

    def test_refresh_sunday_maple_messages_skips_when_event_is_absent(self):
        channel = _FakeTextChannel(channel_id=1234)

        async def fake_fetch_event():
            return None

        async def fake_get_channels(bot, guild_id=None):
            return {10: channel}

        with patch("util.celebration.announcements.get_celebration_channels", fake_get_channels):
            results = asyncio.run(
                refresh_sunday_maple_messages(
                    bot=object(),
                    fetch_event=fake_fetch_event,
                )
            )

        self.assertEqual(results[0].action, "event_absent")
        self.assertEqual(results[0].status, "skipped")
        self.assertEqual(channel.sent_messages, [])

    def test_slash_command_and_help_mention_sunday_maple(self):
        cog_source = Path("cogs/maplestory.py").read_text(encoding="utf-8")
        help_source = Path("cogs/custom_help.py").read_text(encoding="utf-8")

        self.assertIn('name="썬데이메이플"', cog_source)
        self.assertIn("/썬데이메이플", help_source)

    def test_parses_maplestory_notice_list_with_canonical_urls(self):
        notices = parse_maplestory_notice_list(NOTICE_LIST_HTML)

        self.assertEqual([notice.notice_id for notice in notices], ["149371", "149370"])
        self.assertEqual(notices[0].category, "[점검]")
        self.assertEqual(
            notices[0].title,
            "[패치완료] 6/22(월) ver1.2.416 마이너(6) 패치(16:55 적용)",
        )
        self.assertEqual(
            notices[1].url,
            "https://maplestory.nexon.com/News/Notice/149370",
        )

    def test_parses_maplestory_notice_detail_summary(self):
        base_notice = MapleStoryNotice(
            notice_id="149370",
            category="[공지]",
            title="목록 제목",
            url="https://maplestory.nexon.com/News/Notice/149370",
        )

        notice = parse_maplestory_notice_detail(NOTICE_DETAIL_HTML, base_notice)

        self.assertEqual(notice.title, "6/22(월) 사과 보상 안내")
        self.assertEqual(notice.category, "[공지]")
        self.assertEqual(
            notice.summary,
            "불편을 드려 죄송합니다. 7/1(수)까지 수령해 주세요. 더 나은 서비스 제공을 위해 최선을 다하겠습니다.",
        )
        self.assertEqual(
            notice.body_text,
            "안녕하세요. 메이플스토리 입니다. 불편을 드려 죄송합니다. 7/1(수)까지 수령해 주세요. 더 나은 서비스 제공을 위해 최선을 다하겠습니다.",
        )

    def test_maplestory_notice_updates_include_same_id_fingerprint_changes(self):
        original = MapleStoryNotice(
            notice_id="149371",
            category="[점검]",
            title="6/22(월) 서버점검",
            url="https://maplestory.nexon.com/News/Notice/149371",
            summary="오후 4시부터 점검을 진행합니다.",
        )
        changed = MapleStoryNotice(
            notice_id="149371",
            category="[점검]",
            title="[점검완료] 6/22(월) 서버점검",
            url="https://maplestory.nexon.com/News/Notice/149371",
            summary="오후 4시 55분 점검이 완료되었습니다.",
        )
        state = maplestory_notice_state_from_notices([original])

        updates = find_maplestory_notice_updates([changed], state)

        self.assertEqual(updates, [changed])

    def test_builds_maplestory_notice_message(self):
        notice = MapleStoryNotice(
            notice_id="149370",
            category="[공지]",
            title="6/22(월) 사과 보상 안내",
            url="https://maplestory.nexon.com/News/Notice/149370",
            summary="불편을 드려 죄송합니다. 7/1(수)까지 수령해 주세요.",
        )

        self.assertEqual(
            build_maplestory_notice_message(notice),
            "# 공지\n\n"
            "6/22(월) 사과 보상 안내\n"
            "불편을 드려 죄송합니다. 7/1(수)까지 수령해 주세요.\n\n"
            "[바로가기](https://maplestory.nexon.com/News/Notice/149370)",
        )

    def test_builds_maplestory_notice_embed_with_three_summary_lines(self):
        notice = MapleStoryNotice(
            notice_id="149370",
            category="[공지]",
            title="6/22(월) 사과 보상 안내",
            url="https://maplestory.nexon.com/News/Notice/149370",
            summary="불편을 드려 죄송합니다. 7/1(수)까지 수령해 주세요.",
        )

        embed = build_maplestory_notice_embed(
            notice,
            [
                "7/1까지 사과 보상 수령",
                "월드 내 1회 지급",
                "공식 공지에서 상세 확인",
            ],
        )

        self.assertEqual(embed.title, "6/22(월) 사과 보상 안내")
        self.assertEqual(embed.url, notice.url)
        self.assertEqual(
            embed.description,
            "7/1까지 사과 보상 수령\n월드 내 1회 지급\n공식 공지에서 상세 확인",
        )
        self.assertEqual(embed.fields[0].name, "분류")
        self.assertEqual(embed.fields[0].value, "[공지]")

    def test_slash_command_help_and_loop_include_maplestory_notice_subscription(self):
        cog_source = Path("cogs/maplestory.py").read_text(encoding="utf-8")
        help_source = Path("cogs/custom_help.py").read_text(encoding="utf-8")
        loop_source = Path("cogs/loop.py").read_text(encoding="utf-8")

        self.assertIn('name="메이플공지구독"', cog_source)
        self.assertIn('status="상태"', cog_source)
        self.assertIn("/메이플공지구독", help_source)
        self.assertIn("@tasks.loop(minutes=3)", loop_source)
        self.assertIn("maplestory_notice_check", loop_source)


class _FakeSentMessage:
    id = 9876


class _FakeTextChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.sent_messages = []

    async def send(self, **kwargs):
        self.sent_messages.append(kwargs)
        return _FakeSentMessage()


if __name__ == "__main__":
    unittest.main()
