import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from util.maplestory.events import (
    MapleStoryEvent,
    MapleStoryNotice,
    MapleStoryNoticeUpdateResult,
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
    refresh_maplestory_notice_messages,
    refresh_sunday_maple_messages,
)
from util.maplestory.notice_state import remember_maplestory_notice_in_state


MAPLESTORY_EVENTS_PATH = Path("util/maplestory/events.py")
LEGACY_MAPLESTORY_EVENTS_PATH = Path("util/maplestory_events.py")
MAPLESTORY_COG_PATH = Path("cogs/maplestory/__init__.py")
LEGACY_MAPLESTORY_COG_PATH = Path("cogs/maplestory.py")
CUSTOM_HELP_PATH = Path("cogs/custom_help/__init__.py")


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

    def test_maplestory_cog_uses_package_layout(self):
        self.assertTrue(MAPLESTORY_COG_PATH.exists())
        self.assertFalse(LEGACY_MAPLESTORY_COG_PATH.exists())

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
        cog_source = MAPLESTORY_COG_PATH.read_text(encoding="utf-8")
        help_source = CUSTOM_HELP_PATH.read_text(encoding="utf-8")

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
        cog_source = MAPLESTORY_COG_PATH.read_text(encoding="utf-8")
        help_source = CUSTOM_HELP_PATH.read_text(encoding="utf-8")
        loop_source = Path("cogs/loop/__init__.py").read_text(encoding="utf-8")

        self.assertIn('name="메이플공지구독"', cog_source)
        self.assertIn('status="상태"', cog_source)
        self.assertIn("/메이플공지구독", help_source)
        self.assertIn("@tasks.loop(minutes=3)", loop_source)
        self.assertIn("maplestory_notice_check", loop_source)

    def test_refresh_maplestory_notice_messages_edits_tracked_same_id_update(self):
        original = MapleStoryNotice(
            notice_id="149600",
            category="[공지]",
            title="6/30(화) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149600",
            summary="첫 공지입니다.",
        )
        updated = MapleStoryNotice(
            notice_id="149600",
            category="[공지]",
            title="(수정) 6/30(화) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149600",
            summary="수정된 공지입니다.",
        )
        guild_state = maplestory_notice_state_from_notices([original])
        remember_maplestory_notice_in_state(
            guild_state,
            original,
            channel_id=1234,
            message_id=111,
        )
        state = {"guilds": {"10": guild_state}}
        saved_states = []
        bot = _FakeBot()
        previous_message = _FakeNoticeMessage(
            message_id=111,
            author=bot.user,
            title=original.title,
            url=original.url,
        )
        channel = _FakeNoticeChannel(channel_id=1234, messages=[previous_message])
        edited_notices = []

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(saved_state):
            saved_states.append(saved_state)

        async def fake_fetch_notices():
            return [updated]

        async def fake_edit_notice(message, *, guild_id, channel_id, notice):
            edited_notices.append((message.id, notice))
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=message.id,
                action="edited",
            )

        async def fake_send_notice(*args, **kwargs):
            raise AssertionError("same-id update should edit instead of sending")

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.edit_maplestory_notice_message",
            fake_edit_notice,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertEqual(results[0].action, "edited")
        self.assertEqual(results[0].message_id, 111)
        self.assertEqual(edited_notices, [(111, updated)])
        notice_state = saved_states[0]["guilds"]["10"]["notices"]["149600"]
        self.assertEqual(
            [record["messageId"] for record in notice_state["sentMessages"]],
            [111],
        )
        self.assertEqual(notice_state["sentMessages"][0]["title"], updated.title)

    def test_refresh_maplestory_notice_messages_edits_same_id_update_without_modified_title(self):
        original = MapleStoryNotice(
            notice_id="149601",
            category="[공지]",
            title="7/1(수) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149601",
            summary="첫 공지입니다.",
            body_text="첫 본문입니다.",
        )
        updated = MapleStoryNotice(
            notice_id="149601",
            category="[공지]",
            title="7/1(수) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149601",
            summary="수정된 본문입니다.",
            body_text="수정된 본문입니다.",
        )
        guild_state = maplestory_notice_state_from_notices([original])
        remember_maplestory_notice_in_state(
            guild_state,
            original,
            channel_id=1234,
            message_id=211,
        )
        state = {"guilds": {"10": guild_state}}
        bot = _FakeBot()
        previous_message = _FakeNoticeMessage(
            message_id=211,
            author=bot.user,
            title=original.title,
            url=original.url,
        )
        channel = _FakeNoticeChannel(channel_id=1234, messages=[previous_message])
        edited_message_ids = []

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(_saved_state):
            return None

        async def fake_fetch_notices():
            return [updated]

        async def fake_edit_notice(message, *, guild_id, channel_id, notice):
            edited_message_ids.append(message.id)
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=message.id,
                action="edited",
            )

        async def fake_send_notice(*args, **kwargs):
            raise AssertionError("same-id body update should edit instead of sending")

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.edit_maplestory_notice_message",
            fake_edit_notice,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertEqual(results[0].action, "edited")
        self.assertEqual(edited_message_ids, [211])

    def test_refresh_maplestory_notice_messages_sends_completion_and_deletes_previous_messages(self):
        scheduled = MapleStoryNotice(
            notice_id="149602",
            category="[점검]",
            title="[점검예정] 7/2(목) 서버 점검",
            url="https://maplestory.nexon.com/News/Notice/149602",
            summary="오전 10시부터 점검합니다.",
        )
        in_progress = MapleStoryNotice(
            notice_id="149602",
            category="[점검]",
            title="[점검중] 7/2(목) 서버 점검",
            url="https://maplestory.nexon.com/News/Notice/149602",
            summary="점검 중입니다.",
        )
        extended = MapleStoryNotice(
            notice_id="149602",
            category="[점검]",
            title="7/2(목) 서버 연장 점검",
            url="https://maplestory.nexon.com/News/Notice/149602",
            summary="점검이 연장됩니다.",
        )
        completed = MapleStoryNotice(
            notice_id="149602",
            category="[점검]",
            title="[점검완료] 7/2(목) 서버 점검",
            url="https://maplestory.nexon.com/News/Notice/149602",
            summary="점검이 완료되었습니다.",
        )
        guild_state = maplestory_notice_state_from_notices([scheduled])
        remember_maplestory_notice_in_state(
            guild_state,
            scheduled,
            channel_id=1234,
            message_id=311,
        )
        remember_maplestory_notice_in_state(
            guild_state,
            in_progress,
            channel_id=1234,
            message_id=312,
        )
        remember_maplestory_notice_in_state(
            guild_state,
            extended,
            channel_id=1234,
            message_id=313,
        )
        state = {"guilds": {"10": guild_state}}
        saved_states = []
        bot = _FakeBot()
        scheduled_message = _FakeNoticeMessage(
            message_id=311,
            author=bot.user,
            title=scheduled.title,
            url=scheduled.url,
        )
        in_progress_message = _FakeNoticeMessage(
            message_id=312,
            author=bot.user,
            title=in_progress.title,
            url=in_progress.url,
        )
        extended_message = _FakeNoticeMessage(
            message_id=313,
            author=bot.user,
            title=extended.title,
            url=extended.url,
        )
        channel = _FakeNoticeChannel(
            channel_id=1234,
            messages=[extended_message, in_progress_message, scheduled_message],
        )
        sent_notices = []

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(saved_state):
            saved_states.append(saved_state)

        async def fake_fetch_notices():
            return [completed]

        async def fake_edit_notice(*args, **kwargs):
            raise AssertionError("completion update should send a new message")

        async def fake_send_notice(_target, *, guild_id, channel_id, notice):
            sent_notices.append(notice)
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=399,
                action="sent",
            )

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.edit_maplestory_notice_message",
            fake_edit_notice,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertEqual(results[0].action, "sent")
        self.assertEqual(results[0].message_id, 399)
        self.assertEqual(sent_notices, [completed])
        self.assertEqual(results[0].deleted_message_ids, [311, 312, 313])
        self.assertTrue(scheduled_message.deleted)
        self.assertTrue(in_progress_message.deleted)
        self.assertTrue(extended_message.deleted)
        notice_state = saved_states[0]["guilds"]["10"]["notices"]["149602"]
        self.assertEqual(
            [record["messageId"] for record in notice_state["sentMessages"]],
            [399],
        )

    def test_refresh_maplestory_notice_messages_edits_legacy_history_message_without_state_record(self):
        original = MapleStoryNotice(
            notice_id="149603",
            category="[공지]",
            title="7/3(금) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149603",
            summary="첫 공지입니다.",
        )
        updated = MapleStoryNotice(
            notice_id="149603",
            category="[공지]",
            title="(수정) 7/3(금) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149603",
            summary="수정된 공지입니다.",
        )
        state = {"guilds": {"10": maplestory_notice_state_from_notices([original])}}
        bot = _FakeBot()
        previous_message = _FakeNoticeMessage(
            message_id=411,
            author=bot.user,
            title=original.title,
            url=original.url,
        )
        user_message = _FakeNoticeMessage(
            message_id=412,
            author=object(),
            title=original.title,
            url=original.url,
        )
        channel = _FakeNoticeChannel(
            channel_id=1234,
            messages=[previous_message, user_message],
        )
        edited_message_ids = []

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(_saved_state):
            return None

        async def fake_fetch_notices():
            return [updated]

        async def fake_edit_notice(message, *, guild_id, channel_id, notice):
            edited_message_ids.append(message.id)
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=message.id,
                action="edited",
            )

        async def fake_send_notice(*args, **kwargs):
            raise AssertionError("legacy same-url bot message should be edited")

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.edit_maplestory_notice_message",
            fake_edit_notice,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertEqual(results[0].action, "edited")
        self.assertEqual(edited_message_ids, [411])

    def test_refresh_maplestory_notice_messages_sends_when_existing_update_message_is_missing(self):
        original = MapleStoryNotice(
            notice_id="149604",
            category="[공지]",
            title="7/4(토) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149604",
            summary="첫 공지입니다.",
        )
        updated = MapleStoryNotice(
            notice_id="149604",
            category="[공지]",
            title="(수정) 7/4(토) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149604",
            summary="수정된 공지입니다.",
        )
        guild_state = maplestory_notice_state_from_notices([original])
        remember_maplestory_notice_in_state(
            guild_state,
            original,
            channel_id=1234,
            message_id=511,
        )
        state = {"guilds": {"10": guild_state}}
        bot = _FakeBot()
        channel = _FakeNoticeChannel(channel_id=1234, messages=[])
        sent_notices = []

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(_saved_state):
            return None

        async def fake_fetch_notices():
            return [updated]

        async def fake_send_notice(_target, *, guild_id, channel_id, notice):
            sent_notices.append(notice)
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=512,
                action="sent",
            )

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertEqual(results[0].action, "sent")
        self.assertEqual(results[0].message_id, 512)
        self.assertEqual(sent_notices, [updated])

    def test_refresh_maplestory_notice_messages_sends_first_extended_notice(self):
        scheduled = MapleStoryNotice(
            notice_id="149605",
            category="[점검]",
            title="[점검예정] 7/5(일) 서버 점검",
            url="https://maplestory.nexon.com/News/Notice/149605",
            summary="오전 10시부터 점검합니다.",
        )
        extended = MapleStoryNotice(
            notice_id="149605",
            category="[점검]",
            title="7/5(일) 서버 연장 점검 안내",
            url="https://maplestory.nexon.com/News/Notice/149605",
            summary="점검 시간이 연장됩니다.",
        )
        guild_state = maplestory_notice_state_from_notices([scheduled])
        remember_maplestory_notice_in_state(
            guild_state,
            scheduled,
            channel_id=1234,
            message_id=611,
        )
        state = {"guilds": {"10": guild_state}}
        saved_states = []
        bot = _FakeBot()
        previous_message = _FakeNoticeMessage(
            message_id=611,
            author=bot.user,
            title=scheduled.title,
            url=scheduled.url,
        )
        channel = _FakeNoticeChannel(channel_id=1234, messages=[previous_message])
        sent_notices = []

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(saved_state):
            saved_states.append(saved_state)

        async def fake_fetch_notices():
            return [extended]

        async def fake_edit_notice(*args, **kwargs):
            raise AssertionError("first extended notice should send a new message")

        async def fake_send_notice(_target, *, guild_id, channel_id, notice):
            sent_notices.append(notice)
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=612,
                action="sent",
            )

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.edit_maplestory_notice_message",
            fake_edit_notice,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertEqual(results[0].action, "sent")
        self.assertEqual(results[0].message_id, 612)
        self.assertEqual(sent_notices, [extended])
        self.assertFalse(previous_message.deleted)
        notice_state = saved_states[0]["guilds"]["10"]["notices"]["149605"]
        self.assertEqual(
            [record["messageId"] for record in notice_state["sentMessages"]],
            [611, 612],
        )

    def test_refresh_maplestory_notice_messages_edits_existing_extended_notice(self):
        scheduled = MapleStoryNotice(
            notice_id="149606",
            category="[점검]",
            title="[점검예정] 7/6(월) 서버 점검",
            url="https://maplestory.nexon.com/News/Notice/149606",
            summary="오전 10시부터 점검합니다.",
        )
        extended = MapleStoryNotice(
            notice_id="149606",
            category="[점검]",
            title="7/6(월) 서버 연장 점검 안내",
            url="https://maplestory.nexon.com/News/Notice/149606",
            summary="점검 시간이 연장됩니다.",
        )
        updated_extended = MapleStoryNotice(
            notice_id="149606",
            category="[점검]",
            title="(수정) 7/6(월) 서버 연장 점검 안내",
            url="https://maplestory.nexon.com/News/Notice/149606",
            summary="연장 점검 시간이 수정되었습니다.",
        )
        guild_state = maplestory_notice_state_from_notices([scheduled])
        remember_maplestory_notice_in_state(
            guild_state,
            scheduled,
            channel_id=1234,
            message_id=711,
        )
        remember_maplestory_notice_in_state(
            guild_state,
            extended,
            channel_id=1234,
            message_id=712,
        )
        state = {"guilds": {"10": guild_state}}
        bot = _FakeBot()
        scheduled_message = _FakeNoticeMessage(
            message_id=711,
            author=bot.user,
            title=scheduled.title,
            url=scheduled.url,
        )
        extended_message = _FakeNoticeMessage(
            message_id=712,
            author=bot.user,
            title=extended.title,
            url=extended.url,
        )
        channel = _FakeNoticeChannel(
            channel_id=1234,
            messages=[extended_message, scheduled_message],
        )
        edited_message_ids = []

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(_saved_state):
            return None

        async def fake_fetch_notices():
            return [updated_extended]

        async def fake_edit_notice(message, *, guild_id, channel_id, notice):
            edited_message_ids.append(message.id)
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=message.id,
                action="edited",
            )

        async def fake_send_notice(*args, **kwargs):
            raise AssertionError("modified extended notice should edit latest extended message")

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.edit_maplestory_notice_message",
            fake_edit_notice,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertEqual(results[0].action, "edited")
        self.assertEqual(results[0].message_id, 712)
        self.assertEqual(edited_message_ids, [712])
        self.assertFalse(scheduled_message.deleted)
        self.assertFalse(extended_message.deleted)

    def test_refresh_maplestory_notice_messages_deletes_single_tracked_pre_completion_message(self):
        scheduled = MapleStoryNotice(
            notice_id="149500",
            category="[점검]",
            title="[점검예정] 6/25(목) 챌린저스 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149500",
            summary="오전 11시 50분부터 점검합니다.",
        )
        completed = MapleStoryNotice(
            notice_id="149500",
            category="[점검]",
            title="[점검완료] 6/25(목) 챌린저스 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149500",
            summary="점검이 완료되었습니다.",
        )
        guild_state = maplestory_notice_state_from_notices([scheduled])
        remember_maplestory_notice_in_state(
            guild_state,
            scheduled,
            channel_id=1234,
            message_id=111,
        )
        state = {"guilds": {"10": guild_state}}
        saved_states = []
        bot = _FakeBot()
        previous_message = _FakeNoticeMessage(
            message_id=111,
            author=bot.user,
            title=scheduled.title,
            url=scheduled.url,
        )
        channel = _FakeNoticeChannel(channel_id=1234, messages=[previous_message])

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(saved_state):
            saved_states.append(saved_state)

        async def fake_fetch_notices():
            return [completed]

        async def fake_edit_notice(*args, **kwargs):
            raise AssertionError("completion update should send a new message")

        async def fake_send_notice(_target, *, guild_id, channel_id, notice):
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=222,
                action="sent",
            )

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.edit_maplestory_notice_message",
            fake_edit_notice,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertTrue(previous_message.deleted)
        self.assertEqual(results[0].action, "sent")
        self.assertEqual(results[0].message_id, 222)
        self.assertEqual(results[0].deleted_message_ids, [111])
        notice_state = saved_states[0]["guilds"]["10"]["notices"]["149500"]
        self.assertEqual(
            [record["messageId"] for record in notice_state["sentMessages"]],
            [222],
        )

    def test_refresh_maplestory_notice_messages_scans_legacy_history_when_message_ids_are_missing(self):
        scheduled = MapleStoryNotice(
            notice_id="149501",
            category="[점검]",
            title="[점검중] 6/26(금) 전체 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149501",
            summary="점검 진행 중입니다.",
        )
        completed = MapleStoryNotice(
            notice_id="149501",
            category="[점검]",
            title="[점검완료] 6/26(금) 전체 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149501",
            summary="점검이 완료되었습니다.",
        )
        state = {"guilds": {"10": maplestory_notice_state_from_notices([scheduled])}}
        bot = _FakeBot()
        previous_message = _FakeNoticeMessage(
            message_id=333,
            author=bot.user,
            title=scheduled.title,
            url=scheduled.url,
        )
        other_notice_message = _FakeNoticeMessage(
            message_id=334,
            author=bot.user,
            title="[점검중] 다른 공지",
            url="https://maplestory.nexon.com/News/Notice/999999",
        )
        user_message = _FakeNoticeMessage(
            message_id=335,
            author=object(),
            title=scheduled.title,
            url=scheduled.url,
        )
        channel = _FakeNoticeChannel(
            channel_id=1234,
            messages=[previous_message, other_notice_message, user_message],
        )

        async def fake_get_channels_by_purpose(_purpose):
            return {10: 1234}

        async def fake_load_state():
            return state

        async def fake_save_state(_saved_state):
            return None

        async def fake_fetch_notices():
            return [completed]

        async def fake_edit_notice(*args, **kwargs):
            raise AssertionError("legacy completion should send a new message")

        async def fake_send_notice(_target, *, guild_id, channel_id, notice):
            return MapleStoryNoticeUpdateResult(
                guild_id=guild_id,
                channel_id=channel_id,
                notice_id=notice.notice_id,
                message_id=444,
                action="sent",
            )

        async def fake_resolve_channel(_bot, _channel_id):
            return channel

        with patch("util.guild.channel_settings.get_channels_by_purpose", fake_get_channels_by_purpose), patch(
            "util.maplestory.events._load_maplestory_notice_state",
            fake_load_state,
        ), patch(
            "util.maplestory.events._save_maplestory_notice_state",
            fake_save_state,
        ), patch(
            "util.maplestory.events.resolve_text_channel",
            fake_resolve_channel,
        ), patch(
            "util.maplestory.events.edit_maplestory_notice_message",
            fake_edit_notice,
        ), patch(
            "util.maplestory.events.send_maplestory_notice_to_channel",
            fake_send_notice,
        ):
            results = asyncio.run(
                refresh_maplestory_notice_messages(
                    bot=bot,
                    fetch_notices=fake_fetch_notices,
                )
            )

        self.assertTrue(previous_message.deleted)
        self.assertFalse(other_notice_message.deleted)
        self.assertFalse(user_message.deleted)
        self.assertEqual(results[0].action, "sent")
        self.assertEqual(results[0].message_id, 444)
        self.assertEqual(results[0].deleted_message_ids, [333])


class _FakeSentMessage:
    id = 9876


class _FakeTextChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.sent_messages = []

    async def send(self, **kwargs):
        self.sent_messages.append(kwargs)
        return _FakeSentMessage()


class _FakeBot:
    def __init__(self):
        self.user = object()


class _FakeNoticeMessage:
    def __init__(self, *, message_id: int, author: object, title: str, url: str):
        self.id = message_id
        self.author = author
        self.embeds = [_FakeNoticeEmbed(title=title, url=url)]
        self.deleted = False
        self.edits = []

    async def delete(self):
        self.deleted = True

    async def edit(self, *args, **kwargs):
        self.edits.append({"args": args, "kwargs": kwargs})
        embed = kwargs.get("embed")
        if embed is not None:
            self.embeds = [embed]
        return self


class _FakeNoticeEmbed:
    def __init__(self, *, title: str, url: str):
        self.title = title
        self.url = url
        self.fields = []


class _FakeNoticeChannel:
    def __init__(self, *, channel_id: int, messages: list[_FakeNoticeMessage]):
        self.id = channel_id
        self.messages = {message.id: message for message in messages}
        self.history_messages = messages

    async def fetch_message(self, message_id: int):
        message_id = int(message_id)
        if message_id not in self.messages:
            raise ValueError("message not found")
        return self.messages[message_id]

    def history(self, *, limit=None):
        async def iterator():
            for message in self.history_messages[:limit]:
                yield message

        return iterator()


if __name__ == "__main__":
    unittest.main()
