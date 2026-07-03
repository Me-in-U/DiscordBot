import unittest
import warnings
from pathlib import Path

import aiohttp

from util.maplestory.parser import MapleStoryNotice


LIST_HTML = """
<a href="/News/Event/Ongoing/1350">
    <em class="event_listMt">스페셜 썬데이 메이플</em>
</a>
"""

DETAIL_HTML = """
<p class="qs_title"><span>스페셜 썬데이 메이플</span></p>
<span class="event_date">2026년 06월 21일 00시 00분 ~ 2026년 06월 21일 23시 59분</span>
<div class="qs_text"><img src="https://example.com/body.png"></div>
"""

NOTICE_LIST_HTML = """
<a href="/News/Notice/All/149371">
    <em><img src="notice_icon03.png" alt="[점검]" /></em>
    <span>6/22(월) 서버 점검</span>
</a>
"""

NOTICE_LIST_WITH_IGNORED_HTML = """
<a href="/News/Notice/All/149375">
    <em><img src="notice_icon01.png" alt="[공지]" /></em>
    <span>7/3(금) 버그/불법프로그램 신고 보상 안내</span>
</a>
<a href="/News/Notice/All/149374">
    <em><img src="notice_icon01.png" alt="[공지]" /></em>
    <span>Tver.1.2.202 우수테스터 발표 안내</span>
</a>
<a href="/News/Notice/All/149371">
    <em><img src="notice_icon03.png" alt="[점검]" /></em>
    <span>6/22(월) 서버 점검</span>
</a>
"""

NOTICE_DETAIL_HTML = """
<p class="qs_title"><em><img alt="[점검]" /></em><span>[점검완료] 6/22(월) 서버 점검</span></p>
<div class="qs_text"><p>안녕하세요. 메이플스토리입니다.</p><p>점검이 완료되었습니다.</p></div>
"""


MAPLESTORY_FETCHER_PATH = Path("util/maplestory/fetcher.py")
LEGACY_MAPLESTORY_FETCHER_PATH = Path("util/maplestory_fetcher.py")


class MapleStoryFetcherModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_maplestory_fetcher_lives_under_maplestory_package(self):
        self.assertTrue(MAPLESTORY_FETCHER_PATH.exists())
        self.assertFalse(LEGACY_MAPLESTORY_FETCHER_PATH.exists())

    async def test_fetch_sunday_maple_event_uses_parser_module(self):
        from util.maplestory.fetcher import fetch_sunday_maple_event

        requested_urls = []

        async def fake_fetch(url: str) -> str:
            requested_urls.append(url)
            if url.endswith("/News/Event/Ongoing"):
                return LIST_HTML
            return DETAIL_HTML

        event = await fetch_sunday_maple_event(fetch_html=fake_fetch)

        self.assertEqual(
            requested_urls,
            [
                "https://maplestory.nexon.com/News/Event/Ongoing",
                "https://maplestory.nexon.com/News/Event/Ongoing/1350",
            ],
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.image_urls, ["https://example.com/body.png"])

    async def test_fetch_latest_maplestory_notices_keeps_base_notice_on_detail_failure(self):
        from util.maplestory.fetcher import fetch_latest_maplestory_notices

        async def fake_fetch(url: str) -> str:
            if url.endswith("/News/Notice"):
                return NOTICE_LIST_HTML
            raise aiohttp.ClientError("detail failed")

        with self.assertLogs("util.maplestory.fetcher", level="WARNING"):
            notices = await fetch_latest_maplestory_notices(
                fetch_html=fake_fetch,
                limit=1,
            )

        self.assertEqual(
            notices,
            [
                MapleStoryNotice(
                    notice_id="149371",
                    category="[점검]",
                    title="6/22(월) 서버 점검",
                    url="https://maplestory.nexon.com/News/Notice/149371",
                )
            ],
        )

    async def test_fetch_latest_maplestory_notices_hydrates_notice_details(self):
        from util.maplestory.fetcher import fetch_latest_maplestory_notices

        async def fake_fetch(url: str) -> str:
            if url.endswith("/News/Notice"):
                return NOTICE_LIST_HTML
            return NOTICE_DETAIL_HTML

        notices = await fetch_latest_maplestory_notices(
            fetch_html=fake_fetch,
            limit=1,
        )

        self.assertEqual(notices[0].title, "[점검완료] 6/22(월) 서버 점검")
        self.assertEqual(notices[0].summary, "점검이 완료되었습니다.")

    async def test_fetch_latest_maplestory_notices_skips_low_signal_reward_announcements(self):
        from util.maplestory.fetcher import fetch_latest_maplestory_notices

        requested_urls = []

        async def fake_fetch(url: str) -> str:
            requested_urls.append(url)
            if url.endswith("/News/Notice"):
                return NOTICE_LIST_WITH_IGNORED_HTML
            return NOTICE_DETAIL_HTML

        notices = await fetch_latest_maplestory_notices(
            fetch_html=fake_fetch,
            limit=10,
        )

        self.assertEqual([notice.notice_id for notice in notices], ["149371"])
        self.assertEqual(
            requested_urls,
            [
                "https://maplestory.nexon.com/News/Notice",
                "https://maplestory.nexon.com/News/Notice/149371",
            ],
        )


class MapleStoryFetcherCompatibilityTests(unittest.TestCase):
    def test_legacy_maplestory_events_reexports_fetcher_entrypoints(self):
        import util.maplestory.fetcher as maplestory_fetcher
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import util.maplestory.events as maplestory_events

        self.assertIs(
            maplestory_events.fetch_sunday_maple_event,
            maplestory_fetcher.fetch_sunday_maple_event,
        )
        self.assertIs(
            maplestory_events.fetch_latest_maplestory_notices,
            maplestory_fetcher.fetch_latest_maplestory_notices,
        )


if __name__ == "__main__":
    unittest.main()
