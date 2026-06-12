import asyncio
import unittest
from pathlib import Path

from util.maplestory_events import (
    SUNDAY_MAPLE_EVENT_TITLE,
    fetch_sunday_maple_event,
    parse_maplestory_event_detail,
    parse_maplestory_ongoing_event_url,
)


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


class MapleStoryEventTests(unittest.TestCase):
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

    def test_slash_command_and_help_mention_sunday_maple(self):
        cog_source = Path("cogs/maplestory.py").read_text(encoding="utf-8")
        help_source = Path("cogs/custom_help.py").read_text(encoding="utf-8")

        self.assertIn('name="썬데이메이플"', cog_source)
        self.assertIn("/썬데이메이플", help_source)


if __name__ == "__main__":
    unittest.main()
