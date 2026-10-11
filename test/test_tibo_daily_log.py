import json
import os
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

os.environ.setdefault("OPENAI_KEY", "test-key")

from util.codex_resets.tibo import (
    TIBO_URL,
    build_tibo_daily_log_embed,
    fetch_tibo_daily_log,
    parse_tibo_daily_log,
    refresh_tibo_daily_log_notifications,
    reset_tibo_daily_log_state,
    summarize_tibo_daily_log,
)


FIXTURE = Path(__file__).parent / "fixtures" / "tibo_daily_log.html"


class TiboParserTests(unittest.TestCase):
    def setUp(self):
        self.html = FIXTURE.read_text(encoding="utf-8")
        self.entries = parse_tibo_daily_log(self.html)

    def test_reads_announcements_oldest_day_first_and_ignores_waiting_and_votes(self):
        self.assertEqual([entry.day for entry in self.entries], [3, 5])
        latest = self.entries[-1]
        self.assertEqual(latest.title, "Sample & improvement")
        self.assertEqual(latest.description, "A new feature is available.")
        self.assertEqual(latest.date, "2026-10-09")
        self.assertEqual(latest.source_url, "https://x.com/thsottiaux/status/500")

    def test_votes_and_whitespace_do_not_change_fingerprint(self):
        changed = parse_tibo_daily_log(self.html.replace(">74<", ">2000<").replace("is available.", "is   available."))
        self.assertEqual([entry.fingerprint() for entry in changed], [entry.fingerprint() for entry in self.entries])
        changed_title = replace(self.entries[-1], title="Corrected title")
        self.assertNotEqual(changed_title.fingerprint(), self.entries[-1].fingerprint())

    def test_rejects_missing_markup_invalid_dates_and_incomplete_entries(self):
        for html in (
            "<html>Unavailable</html>",
            '<ol class="challenge-ledger"></ol>',
            self.html.replace("2026-10-09", "invalid"),
            self.html.replace("Sample &amp; improvement", ""),
            self.html.replace("day-5", "day-29"),
            self.html.replace("announcement-post%3A500", "announcement-post%3A300"),
            self.html.replace("challenge-entry--improvement", "challenge-entry--unknown"),
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                parse_tibo_daily_log(html)

    def test_only_waiting_days_is_valid_empty_log(self):
        html = '<ol class="challenge-ledger"><li class="challenge-row" id="day-1"><time datetime="2026-10-05"></time>Waiting for Tibo</li></ol>'
        self.assertEqual(parse_tibo_daily_log(html), ())

    def test_reset_articles_without_type_class_use_preceding_badge(self):
        html = self.html.replace(
            '<article id="announcement-post%3A300" class="challenge-entry challenge-entry--reset">',
            '<span class="challenge-badge challenge-state--reset">Reset</span>'
            '<article id="announcement-post%3A300" class="challenge-entry">',
        )
        self.assertEqual(parse_tibo_daily_log(html), self.entries)
        banked = parse_tibo_daily_log(html.replace(">Reset</span>", ">Banked reset</span>"))
        self.assertEqual(banked[0].kind, "banked-reset")
        self.assertEqual(banked[1].kind, "improvement")

    def test_untrusted_source_uses_tracker_link(self):
        entries = parse_tibo_daily_log(self.html.replace("https://x.com/thsottiaux/status/500", "javascript:alert(1)"))
        self.assertEqual(entries[-1].source_url, f"{TIBO_URL}#announcement-post%3A500")

    def test_embed_has_separate_design_and_bounded_content(self):
        improvement = build_tibo_daily_log_embed((self.entries[-1],), (("한국어 제목", "한국어 요약"),), updated=True)
        reset = build_tibo_daily_log_embed((self.entries[0],), (("리셋", "사용량이 초기화되었습니다."),))
        self.assertEqual(improvement.color.value, 0x9B8AFB)
        self.assertEqual(reset.color.value, 0xF28C45)
        self.assertIn("Day 05 / 28", improvement.title)
        self.assertEqual(improvement.fields[-1].value, "Daily log 갱신")
        self.assertIn("원문 발표", improvement.fields[0].value)
        bounded = build_tibo_daily_log_embed((self.entries[-1],), (("*" * 10000, "*" * 10000),))
        self.assertLessEqual(len(bounded.fields[0].name), 256)
        self.assertLessEqual(len(bounded.fields[0].value), 1024)
        self.assertLessEqual(len(bounded), 6000)

    def test_mixed_day_keeps_all_items_in_one_embed(self):
        entries = tuple(replace(entry, day=5, date="2026-10-09") for entry in self.entries)
        embed = build_tibo_daily_log_embed(entries, (("한국어 리셋", "리셋 요약"), ("한국어 개선", "개선 요약")))
        self.assertEqual(embed.color.value, 0xF2C14E)
        self.assertEqual(len(embed.fields), 4)
        self.assertIn("한국어 리셋", embed.fields[0].name)
        self.assertIn("한국어 개선", embed.fields[1].name)


class TiboNotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.entries = parse_tibo_daily_log(FIXTURE.read_text(encoding="utf-8"))
        self.channels = AsyncMock(return_value={10: 100})
        self.fetch = AsyncMock(return_value=self.entries)
        self.load = AsyncMock(return_value=None)
        self.execute = AsyncMock()
        self.target = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=1)))
        self.resolve = AsyncMock(return_value=self.target)
        self.summarize = AsyncMock(side_effect=lambda entries: tuple(("한국어 제목", "한국어 요약") for entry in entries))
        for name, mock in (
            ("get_channels_by_purpose", self.channels),
            ("fetch_tibo_daily_log", self.fetch),
            ("fetch_one", self.load),
            ("execute_query", self.execute),
            ("resolve_codex_reset_channel", self.resolve),
            ("summarize_tibo_daily_log", self.summarize),
        ):
            patcher = patch(f"util.codex_resets.tibo.{name}", mock)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_state(self, entries, channel_id=100):
        self.load.return_value = {"setting_value": json.dumps({
            "channelId": channel_id,
            "entries": {entry.entry_id: entry.fingerprint() for entry in entries},
        })}

    async def test_first_poll_seeds_without_sending_history(self):
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 0)
        self.channels.assert_awaited_once_with("codex_reset")
        self.target.send.assert_not_awaited()
        self.summarize.assert_not_awaited()
        key, payload = self.execute.call_args.args[1]
        self.assertEqual(key, "tiboDailyLog:10")
        self.assertEqual(len(json.loads(payload)["entries"]), 2)

    async def test_new_and_edited_entries_send_and_persist(self):
        self.set_state([self.entries[0]])
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 1)
        self.resolve.assert_awaited_once_with(unittest.mock.ANY, 100)
        self.assertEqual(self.target.send.call_args.kwargs["embed"].fields[-1].value, "새 Daily log")
        saved = self.execute.call_args.args[1][1]
        self.load.return_value = {"setting_value": saved}
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 0)
        self.fetch.return_value = (self.entries[0], replace(self.entries[-1], description="Corrected description"))
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 1)
        self.assertEqual(self.target.send.call_args.kwargs["embed"].fields[-1].value, "Daily log 갱신")

    async def test_one_changed_item_sends_entire_day_once(self):
        first = self.entries[-1]
        second = replace(first, entry_id="second", title="Second announcement")
        third = replace(first, entry_id="third", title="Third announcement")
        self.set_state([first, second])
        self.fetch.return_value = (first, second, third)
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 1)
        self.assertEqual(self.target.send.await_count, 2)
        self.assertEqual(self.target.send.await_args_list[0].kwargs["content"], "추가 개선 사항 업데이트")
        self.assertIn("embed", self.target.send.await_args_list[1].kwargs)
        self.summarize.assert_awaited_once_with((first, second, third))
        embed = self.target.send.call_args.kwargs["embed"]
        self.assertEqual(len(embed.fields), 5)
        self.assertIn("3건", embed.description)
        saved = json.loads(self.execute.call_args.args[1][1])
        self.assertEqual(len(saved["entries"]), 3)

    async def test_update_notice_lists_only_changed_types_and_bolds_banked_reset(self):
        unchanged = self.entries[-1]
        reset = replace(unchanged, entry_id="new-reset", kind="reset")
        banked = replace(unchanged, entry_id="new-banked", kind="banked-reset")
        self.set_state([unchanged])
        self.fetch.return_value = (unchanged, reset, banked)
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 1)
        self.assertEqual(self.target.send.await_args_list[0].kwargs["content"], "추가 **적립형 리셋**, 리셋 사항 업데이트")
        self.assertIn("embed", self.target.send.await_args_list[1].kwargs)

    async def test_notice_failure_stops_embed_and_keeps_state(self):
        self.set_state(self.entries)
        self.fetch.return_value = (self.entries[0], replace(self.entries[-1], description="Updated description"))
        self.target.send.side_effect = RuntimeError("Notice failed")
        with self.assertLogs("util.codex_resets.tibo", level="ERROR"):
            self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 0)
        self.target.send.assert_awaited_once()
        self.assertEqual(self.target.send.call_args.kwargs["content"], "추가 개선 사항 업데이트")
        self.execute.assert_not_awaited()

    async def test_translation_failure_keeps_state_for_retry(self):
        self.set_state([])
        self.summarize.side_effect = ValueError("Invalid translation")
        with self.assertLogs("util.codex_resets.tibo", level="ERROR"):
            self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 0)
        self.execute.assert_not_awaited()
        self.target.send.assert_not_awaited()

    async def test_translates_each_day_once_for_multiple_guilds(self):
        self.channels.return_value = {10: 100, 20: 200}
        self.load.side_effect = [
            {"setting_value": json.dumps({"channelId": channel, "entries": {}})}
            for channel in (100, 200)
        ]
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 4)
        self.assertEqual(self.summarize.await_count, 2)

    async def test_channel_change_reseeds_without_history(self):
        self.set_state([], channel_id=99)
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 0)
        self.target.send.assert_not_awaited()
        self.execute.assert_awaited_once()

    async def test_send_failure_retries_and_does_not_advance_state(self):
        self.set_state([])
        self.target.send.side_effect = RuntimeError("Forbidden")
        with self.assertLogs("util.codex_resets.tibo", level="ERROR"):
            self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 0)
        self.execute.assert_not_awaited()
        self.target.send.side_effect = None
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 2)

    async def test_failed_guild_does_not_block_other_guilds(self):
        self.channels.return_value = {10: 100, 20: 200}
        self.set_state([], channel_id=200)
        self.load.side_effect = [RuntimeError("DB unavailable"), self.load.return_value]
        with self.assertLogs("util.codex_resets.tibo", level="ERROR"):
            self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 2)
        self.resolve.assert_awaited_once_with(unittest.mock.ANY, 200)

    async def test_save_failure_stops_remaining_entries(self):
        self.set_state([])
        self.execute.side_effect = RuntimeError("DB unavailable")
        with self.assertLogs("util.codex_resets.tibo", level="ERROR"):
            self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 0)
        self.target.send.assert_awaited_once()

    async def test_no_channels_skips_fetch(self):
        self.channels.return_value = {}
        self.assertEqual(await refresh_tibo_daily_log_notifications(object()), 0)
        self.fetch.assert_not_awaited()

    async def test_fetch_failure_does_not_modify_state(self):
        self.fetch.side_effect = ValueError("Markup changed")
        with self.assertRaises(ValueError):
            await refresh_tibo_daily_log_notifications(object())
        self.load.assert_not_awaited()
        self.execute.assert_not_awaited()

    async def test_configuration_clears_daily_log_state(self):
        await reset_tibo_daily_log_state(10)
        self.execute.assert_awaited_once_with("DELETE FROM setting_data WHERE setting_key = %s", ("tiboDailyLog:10",))


class TiboFetcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_uses_page_and_checks_http_status(self):
        response = SimpleNamespace(raise_for_status=unittest.mock.Mock(), text=AsyncMock(return_value=FIXTURE.read_text(encoding="utf-8")))
        session = MagicMock()
        session.get.return_value.__aenter__.return_value = response
        with patch("util.codex_resets.tibo.aiohttp.ClientSession") as client:
            client.return_value.__aenter__.return_value = session
            entries = await fetch_tibo_daily_log()
            response.raise_for_status.side_effect = aiohttp.ClientResponseError(
                request_info=MagicMock(), history=(), status=429,
            )
            with self.assertRaises(aiohttp.ClientResponseError) as error:
                await fetch_tibo_daily_log()
            self.assertEqual(error.exception.status, 429)
        self.assertEqual(len(entries), 2)
        self.assertEqual(response.raise_for_status.call_count, 2)
        response.text.assert_awaited_once()
        self.assertEqual(session.get.call_args.args[0], TIBO_URL)


class TiboSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_dedicated_structured_prompt_and_preserves_all_items(self):
        entries = parse_tibo_daily_log(FIXTURE.read_text(encoding="utf-8"))
        translated = json.dumps({"announcements": [{"title": "한국어 제목", "summary": "한국어 요약입니다."} for entry in entries]})
        with patch("api.chatGPT.custom_prompt_model", return_value=translated) as translate:
            summaries = await summarize_tibo_daily_log(entries)
        self.assertEqual(len(summaries), len(entries))
        self.assertEqual(len(json.loads(translate.call_args.kwargs["image_content"][0]["content"][0]["text"])), len(entries))
        self.assertEqual(
            translate.call_args.kwargs["prompt"],
            {"id": "pmpt_6acb1292a3d081949de6159ba2e7b8980f0a4220cb94db05", "version": "1"},
        )
        self.assertNotIn("instructions", translate.call_args.kwargs)

    async def test_missing_items_or_invalid_response_fail_instead_of_sending(self):
        entries = parse_tibo_daily_log(FIXTURE.read_text(encoding="utf-8"))
        for response in (
            "not json", "[]", '{"announcements":[]}',
            '{"announcements":[{"title":"title","summary":"English"},{"title":"title","summary":"English"}]}',
            '{"announcements":[{"title":"한국어 제목","summary":null},{"title":"한국어 제목","summary":"한국어 요약"}]}',
        ):
            with self.subTest(response=response), patch("api.chatGPT.custom_prompt_model", return_value=response):
                with self.assertRaises(ValueError):
                    await summarize_tibo_daily_log(entries)
