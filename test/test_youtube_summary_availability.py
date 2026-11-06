import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("OPENAI_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from func.youtube_api import YouTubeApiError, YouTubeLiveInProgress, YouTubeSummaryUnavailable, check_video_summary_available
from func.youtube_summary_ui import YouTubeSummaryView, check_youtube_link


class VideoAvailabilityTests(unittest.TestCase):
    def check_item(self, item):
        youtube = Mock()
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [] if item is None else [item]
        }
        with patch("func.youtube_api._build_youtube_client", return_value=youtube):
            check_video_summary_available("video-id")
        youtube.videos.return_value.list.assert_called_once_with(
            part="snippet,liveStreamingDetails,status,contentDetails", id="video-id"
        )

    def test_unavailable_states(self):
        cases = [
            (None, "삭제, 비공개 또는 접근 제한"),
            ({"snippet": {"liveBroadcastContent": "live"}}, "진행 중"),
            ({"liveStreamingDetails": {"actualStartTime": "2026-01-01T00:00:00Z"}}, "진행 중"),
            ({"snippet": {"liveBroadcastContent": "upcoming"}}, "아직 제공되지"),
            ({"status": {"privacyStatus": "private"}}, "비공개"),
            ({"status": {"uploadStatus": "deleted"}}, "삭제된"),
            ({"status": {"uploadStatus": "failed"}}, "업로드에 실패"),
            ({"status": {"uploadStatus": "rejected"}}, "거부"),
            ({"status": {"uploadStatus": "uploaded"}}, "처리 중"),
            ({"liveStreamingDetails": {"actualEndTime": "2026-01-01T00:00:00Z"}, "contentDetails": {"duration": "PT0S"}}, "다시보기가 아직 준비되지"),
        ]
        for item, expected in cases:
            with self.subTest(item=item):
                with self.assertRaises(YouTubeSummaryUnavailable) as caught:
                    self.check_item(item)
                self.assertIn(expected, str(caught.exception))

    def test_schedule_time_and_invalid_time(self):
        for value, expected in [
            ("2099-01-01T00:00:00Z", "2099-01-01 09:00 (한국 시간)"),
            ("2000-01-01T00:00:00Z", "예정 시간이 지났지만"),
            ("invalid", "예정 시간을 확인할 수 없습니다"),
            ("2099-01-01T00:00:00", "예정 시간을 확인할 수 없습니다"),
        ]:
            for part, field in [("liveStreamingDetails", "scheduledStartTime"), ("status", "publishAt")]:
                with self.subTest(value=value, part=part):
                    with self.assertRaises(YouTubeSummaryUnavailable) as caught:
                        self.check_item({part: {field: value}})
                    self.assertIn(expected, str(caught.exception))

    def test_regular_unlisted_and_completed_archive_are_allowed(self):
        self.check_item({"status": {"privacyStatus": "unlisted", "uploadStatus": "processed"}})
        self.check_item({
            "liveStreamingDetails": {"actualStartTime": "2000-01-01T00:00:00Z", "actualEndTime": "2000-01-01T00:10:00Z"},
            "contentDetails": {"duration": "PT10M"},
        })


class AvailabilityEntryPointTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_link_is_silent_but_direct_request_keeps_reason(self):
        message = Mock(content="https://youtube.com/live/video-id")
        message.reply = AsyncMock()
        youtube = Mock()
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"snippet": {"liveBroadcastContent": "live"}}]
        }
        with patch("func.youtube_api._build_youtube_client", return_value=youtube):
            await check_youtube_link(message)
            from func.youtube_processor import process_youtube_link
            with self.assertRaisesRegex(YouTubeLiveInProgress, "진행 중"):
                await process_youtube_link("https://youtube.com/live/video-id")
        message.reply.assert_not_awaited()

    async def test_automatic_unavailable_reply_has_no_button(self):
        message = Mock(content="https://youtube.com/live/video-id")
        message.reply = AsyncMock()
        with patch("func.youtube_summary_ui.check_video_summary_available", side_effect=YouTubeSummaryUnavailable("예약: 공개 예정 시간")):
            await check_youtube_link(message)
        message.reply.assert_awaited_once_with(content="예약: 공개 예정 시간")

    async def test_automatic_api_failure_suppresses_prompt(self):
        message = Mock(content="https://youtu.be/video-id")
        message.reply = AsyncMock()
        with patch("func.youtube_summary_ui.check_video_summary_available", side_effect=YouTubeApiError("failure")):
            with self.assertLogs("func.youtube_summary_ui", level="WARNING"):
                await check_youtube_link(message)
        message.reply.assert_not_awaited()

    async def test_post_does_not_query_video_api(self):
        message = Mock(content="https://youtube.com/post/UgTest")
        message.reply = AsyncMock()
        with patch("func.youtube_summary_ui.check_video_summary_available") as check:
            await check_youtube_link(message)
        check.assert_not_called()
        self.assertIn("view", message.reply.await_args.kwargs)

    async def test_processor_blocks_before_download_and_keeps_reason(self):
        from func.youtube_processor import process_youtube_link
        with patch("func.youtube_processor.check_video_summary_available", side_effect=YouTubeLiveInProgress("라이브 진행 중")) as check:
            with patch("func.youtube_processor.download_youtube_subtitles") as download:
                with self.assertRaisesRegex(YouTubeSummaryUnavailable, "라이브 진행 중"):
                    await process_youtube_link("https://youtu.be/video-id")
        check.assert_called_once_with("video-id")
        download.assert_not_called()

    async def test_old_button_shows_reason_without_error_button(self):
        view = YouTubeSummaryView("https://youtu.be/video-id", "video", processor=AsyncMock(side_effect=YouTubeLiveInProgress("라이브 진행 중")))
        view.original_message = Mock(edit=AsyncMock())
        interaction = Mock()
        interaction.response.defer = AsyncMock()
        await view.children[0].callback(interaction)
        view.original_message.edit.assert_awaited_with(content="라이브 진행 중", view=None)

    async def test_context_menu_shows_reason(self):
        from cogs.summarize import summarize_youtube_message_context_menu
        interaction = Mock(edit_original_response=AsyncMock())
        interaction.response.defer = AsyncMock()
        with patch("cogs.summarize.extract_first_youtube_link", return_value="https://youtu.be/video-id"):
            with patch("cogs.summarize.process_youtube_link", side_effect=YouTubeSummaryUnavailable("예약 시간 안내")):
                await summarize_youtube_message_context_menu.callback(interaction, Mock())
        interaction.edit_original_response.assert_awaited_once_with(content="예약 시간 안내")

    async def test_slash_selection_shows_reason(self):
        from cogs.summarize import YouTubeSummarySelectionView
        from func.youtube_summary import YouTubeLinkCandidate
        view = YouTubeSummarySelectionView([YouTubeLinkCandidate("https://youtu.be/video-id", "video", "title")], 123, "선택")
        view.original_message = Mock(edit=AsyncMock())
        select = view.children[0]
        select._values = ["0"]
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.edit_message = AsyncMock()
        with patch("cogs.summarize.process_youtube_link", side_effect=YouTubeLiveInProgress("라이브 진행 중")):
            await select.callback(interaction)
        view.original_message.edit.assert_awaited_once_with(content="라이브 진행 중", view=None)
