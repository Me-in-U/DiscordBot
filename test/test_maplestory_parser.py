import unittest
import warnings
from pathlib import Path


LIST_HTML = """
<div class="event_list_wrap">
    <a href="/News/Event/Ongoing/1350">
        <em class="event_listMt">스페셜 썬데이 메이플</em>
    </a>
</div>
"""

DETAIL_HTML = """
<p class="qs_title"><span> 스페셜 썬데이 메이플</span></p>
<span class="event_date">2026년 06월 21일 00시 00분 ~ 2026년 06월 21일 23시 59분</span>
<div class="qs_text">
    <img src="/event/body.png">
    <img src="/event/body.png">
</div>
"""

NOTICE_HTML = """
<ul class="news_board">
    <li>
        <a href="/News/Notice/All/149371">
            <em><img src="notice_icon03.png" alt="[점검]" /></em>
            <span>[패치완료] 6/22(월) 점검 완료</span>
        </a>
    </li>
</ul>
"""


MAPLESTORY_PARSER_PATH = Path("util/maplestory/parser.py")
LEGACY_MAPLESTORY_PARSER_PATH = Path("util/maplestory_parser.py")


class MapleStoryParserModuleTests(unittest.TestCase):
    def test_maplestory_parser_lives_under_maplestory_package(self):
        self.assertTrue(MAPLESTORY_PARSER_PATH.exists())
        self.assertFalse(LEGACY_MAPLESTORY_PARSER_PATH.exists())

    def test_parser_module_exposes_event_and_notice_parsers(self):
        from util.maplestory.parser import (
            SUNDAY_MAPLE_EVENT_TITLE,
            MapleStoryNotice,
            parse_maplestory_event_detail,
            parse_maplestory_notice_list,
            parse_maplestory_ongoing_event_url,
        )

        event_url = parse_maplestory_ongoing_event_url(LIST_HTML)
        self.assertEqual(
            event_url,
            "https://maplestory.nexon.com/News/Event/Ongoing/1350",
        )

        event = parse_maplestory_event_detail(DETAIL_HTML, event_url=event_url)
        self.assertEqual(event.title, SUNDAY_MAPLE_EVENT_TITLE)
        self.assertEqual(
            event.image_urls,
            ["https://maplestory.nexon.com/event/body.png"],
        )

        notices = parse_maplestory_notice_list(NOTICE_HTML)
        self.assertEqual(
            notices,
            [
                MapleStoryNotice(
                    notice_id="149371",
                    category="[점검]",
                    title="[패치완료] 6/22(월) 점검 완료",
                    url="https://maplestory.nexon.com/News/Notice/149371",
                )
            ],
        )

    def test_legacy_maplestory_events_reexports_parser_entrypoints(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import util.maplestory_events as maplestory_events
        import util.maplestory.parser as maplestory_parser

        self.assertIs(maplestory_events.MapleStoryEvent, maplestory_parser.MapleStoryEvent)
        self.assertIs(
            maplestory_events.MapleStoryNotice,
            maplestory_parser.MapleStoryNotice,
        )
        self.assertIs(
            maplestory_events.parse_maplestory_ongoing_event_url,
            maplestory_parser.parse_maplestory_ongoing_event_url,
        )
        self.assertIs(
            maplestory_events.parse_maplestory_event_detail,
            maplestory_parser.parse_maplestory_event_detail,
        )
        self.assertIs(
            maplestory_events.parse_maplestory_notice_list,
            maplestory_parser.parse_maplestory_notice_list,
        )
        self.assertIs(
            maplestory_events.parse_maplestory_notice_detail,
            maplestory_parser.parse_maplestory_notice_detail,
        )


if __name__ == "__main__":
    unittest.main()
