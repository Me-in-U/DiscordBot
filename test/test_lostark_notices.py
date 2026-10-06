import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from util.lostark.notices import (
    LOSTARK_NOTICE_CHANNEL_TYPE,
    LOSTARK_NOTICE_STATE_KEY,
    configure_lostark_notice_channel,
    fetch_latest_lostark_notices,
    parse_lostark_notice_detail,
    parse_lostark_notice_list,
    run_lostark_notice_loop,
)
from util.maplestory.notice_state import (
    find_maplestory_notice_updates,
    maplestory_notice_state_from_notices,
)
from util.maplestory.sender import build_maplestory_notice_embed, summarize_maplestory_notice_with_openai

LIST_HTML = """
<a href="/News/Notice/Views/999">배너</a>
<li><a href="/News/Notice/NoticeViews/10?page=1">
<div class="list__category"><span>공지</span></div>
<span class="list__title">알려진 이슈</span></a></li>
<li><a href="/News/Notice/Views/12?page=1">
<div class="list__category"><span>점검</span></div>
<span class="list__title">정기 점검 안내</span><span>새 글</span>
<div class="list__read">123</div><span>3시간 전</span></a></li>
<li><a href="/News/Notice/Views/10?page=1">
<span class="list__title">알려진 이슈</span></a></li>
"""
DETAIL_HTML = """
<h2><span class="article__category"><span>점검</span></span>
<span class="article__title">정기 점검 안내</span><span>새 글</span></h2>
<div class="article__read">조회수 123</div>
<div class="article__nav"><a href="/News/Notice/Views/10">이전 글</a></div>
<section class="article__data"><div class="fr-view">
<p>안녕하세요, 로스트아크입니다.</p>
<p>[점검 시간]<br>06:00 ~ 10:00</p>
<p>서비스 안정화 <a href="/News/Notice/Views/10">안내 링크</a></p>
<script>ignored()</script><img src="image.jpg" />
</div></section><footer>사이트 메뉴</footer>
"""


class LostArkNoticeTests(unittest.IsolatedAsyncioTestCase):
    def test_list_deduplicates_pins_and_ignores_banners_and_relative_dates(self):
        notices = parse_lostark_notice_list(LIST_HTML)
        self.assertEqual([n.notice_id for n in notices], ["12", "10"])
        self.assertEqual(notices[0].title, "정기 점검 안내")
        self.assertEqual(notices[0].category, "점검")
        self.assertTrue(notices[0].url.endswith("/Views/12"))

    def test_detail_keeps_header_and_body_links_without_navigation_noise(self):
        notice = parse_lostark_notice_detail(DETAIL_HTML, parse_lostark_notice_list(LIST_HTML)[0])
        self.assertEqual(notice.title, "정기 점검 안내")
        self.assertEqual(notice.category, "점검")
        self.assertIn("06:00 ~ 10:00", notice.body_text)
        self.assertIn("안내 링크", notice.body_text)
        for noise in ("조회수", "사이트 메뉴", "ignored", "이전 글"):
            self.assertNotIn(noise, notice.body_text)
        embed = build_maplestory_notice_embed(notice, ["일정 안내", "서비스 안정화", "세부 내용은 링크에서 확인."])
        self.assertEqual(embed.author.name, "로스트아크 공지")
        self.assertEqual(embed.footer.text, "출처: 로스트아크 공식 공지")

    def test_full_body_changes_beyond_summary_are_detected(self):
        notice = parse_lostark_notice_detail(DETAIL_HTML, parse_lostark_notice_list(LIST_HTML)[0])
        state = maplestory_notice_state_from_notices([notice])
        self.assertEqual(find_maplestory_notice_updates([notice], state), [])
        changed = replace(notice, body_text=notice.body_text + " 점검 연장 안내")
        self.assertEqual(find_maplestory_notice_updates([changed], state), [changed])

    async def test_image_only_notice_is_valid_and_image_changes_are_detected(self):
        html = '<section class="article__data"><div class="fr-view"><p><img src="//cdn-lostark.game.onstove.com/event.jpg"></p><p>&nbsp;<br></p></div></section>'
        fetch = AsyncMock(side_effect=[LIST_HTML, html])
        notices = await fetch_latest_lostark_notices(fetch, limit=1)
        notice = notices[0]
        self.assertIn("이미지로 작성된 공지", notice.summary)
        self.assertIn("https://cdn-lostark.game.onstove.com/event.jpg", notice.body_text)
        state = maplestory_notice_state_from_notices(notices)
        changed = parse_lostark_notice_detail(html.replace("event.jpg", "updated.jpg"), notice)
        self.assertEqual(find_maplestory_notice_updates([changed], state), [changed])

    async def test_failed_detail_does_not_return_a_partial_empty_body(self):
        fetch = AsyncMock(side_effect=[LIST_HTML, "<html>일시적인 오류</html>"])
        with self.assertRaises(ValueError):
            await fetch_latest_lostark_notices(fetch, limit=1)

    async def test_summary_uses_lostark_prompt_and_completed_fallback(self):
        notice = parse_lostark_notice_detail(DETAIL_HTML, parse_lostark_notice_list(LIST_HTML)[0])
        calls = []

        def generate(*args):
            calls.append(args)
            return "일정 안내\n서비스 안정화\n세부 내용은 링크에서 확인."

        await summarize_maplestory_notice_with_openai(notice, generate_text=generate)
        self.assertIn("로스트아크 공식 공지", calls[0][1])
        self.assertNotIn("메이플스토리", calls[0][1])

        def unavailable(*args):
            raise RuntimeError("offline")

        lines = await summarize_maplestory_notice_with_openai(
            replace(notice, title="임시 점검 완료 안내"), generate_text=unavailable,
        )
        self.assertEqual(lines[0], "점검 완료 안내입니다.")

    async def test_enable_seeds_before_changing_channel(self):
        with patch("util.lostark.notices.seed_maplestory_notice_state_for_guild", new_callable=AsyncMock) as seed, patch("util.lostark.notices.set_channel", new_callable=AsyncMock) as set_channel:
            await configure_lostark_notice_channel(1, 2)
            self.assertEqual(seed.await_args.kwargs["state_key"], LOSTARK_NOTICE_STATE_KEY)
            set_channel.assert_awaited_once_with(1, LOSTARK_NOTICE_CHANNEL_TYPE, 2)

    async def test_seed_failure_keeps_channel_setting(self):
        with patch("util.lostark.notices.seed_maplestory_notice_state_for_guild", new_callable=AsyncMock, side_effect=ValueError("offline")), patch("util.lostark.notices.set_channel", new_callable=AsyncMock) as set_channel:
            with self.assertRaises(ValueError):
                await configure_lostark_notice_channel(1, 2)
            set_channel.assert_not_awaited()

    async def test_disable_removes_only_target_guild_state(self):
        state = {"guilds": {"1": {"notices": {}}, "3": {"notices": {}}}}
        with patch("util.lostark.notices._load_maplestory_notice_state", new_callable=AsyncMock, return_value=state), patch("util.lostark.notices._save_maplestory_notice_state", new_callable=AsyncMock) as save, patch("util.lostark.notices.set_channel", new_callable=AsyncMock) as set_channel:
            await configure_lostark_notice_channel(1, None)
            self.assertEqual(state["guilds"], {"3": {"notices": {}}})
            save.assert_awaited_once_with(state, LOSTARK_NOTICE_STATE_KEY)
            set_channel.assert_awaited_once_with(1, LOSTARK_NOTICE_CHANNEL_TYPE, None)

    async def test_polling_uses_independent_channel_and_state(self):
        with patch("util.lostark.notices.refresh_maplestory_notice_messages", new_callable=AsyncMock, return_value=[]) as refresh:
            await run_lostark_notice_loop(object())
            self.assertEqual(refresh.await_args.kwargs["channel_type"], LOSTARK_NOTICE_CHANNEL_TYPE)
            self.assertEqual(refresh.await_args.kwargs["state_key"], LOSTARK_NOTICE_STATE_KEY)

    def test_command_settings_help_and_loop_are_connected(self):
        cog = Path("cogs/lostark/__init__.py").read_text(encoding="utf-8")
        settings = Path("cogs/channel_settings/__init__.py").read_text(encoding="utf-8")
        help_text = Path("cogs/custom_help/__init__.py").read_text(encoding="utf-8")
        loop = Path("cogs/loop/__init__.py").read_text(encoding="utf-8")
        self.assertIn('name="로아공지구독"', cog)
        self.assertIn("guild_permissions.administrator", cog)
        self.assertIn('app_commands.rename(status="상태")', cog)
        self.assertIn('app_commands.Choice(name="로아공지", value="lostark_notice")', settings)
        self.assertIn("configure_lostark_notice_channel", settings)
        self.assertIn("`/로아공지구독 [상태]`", help_text)
        self.assertIn('"lostark_notice_check",', loop)


if __name__ == "__main__":
    unittest.main()
