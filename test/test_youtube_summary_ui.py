import asyncio
import unittest

from func.youtube_links import YOUTUBE_POST_KIND, YOUTUBE_VIDEO_KIND
from func.youtube_summary_ui import (
    check_youtube_link,
    get_youtube_prompt_text,
    get_youtube_summary_title,
)


class YouTubeSummaryUiTests(unittest.TestCase):
    def test_prompt_and_title_reflect_link_kind(self):
        self.assertEqual(
            get_youtube_prompt_text(YOUTUBE_POST_KIND),
            "유튜브 게시물 요약을 진행하시겠습니까?",
        )
        self.assertEqual(
            get_youtube_prompt_text(YOUTUBE_VIDEO_KIND),
            "유튜브 영상 요약을 진행하시겠습니까?",
        )
        self.assertEqual(get_youtube_summary_title(YOUTUBE_POST_KIND), "**[게시물 요약]**")
        self.assertEqual(get_youtube_summary_title(YOUTUBE_VIDEO_KIND), "**[영상 3줄 요약]**")

    def test_check_youtube_link_replies_with_summary_view(self):
        message = _FakeMessage("확인 https://youtu.be/test-video")

        asyncio.run(check_youtube_link(message, processor=_fake_processor))

        self.assertEqual(
            message.replies[0]["content"],
            "유튜브 영상 요약을 진행하시겠습니까?",
        )
        view = message.replies[0]["view"]
        self.assertEqual(view.youtube_url, "https://youtu.be/test-video")
        self.assertEqual(view.link_kind, YOUTUBE_VIDEO_KIND)


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content
        self.replies = []

    async def reply(self, **kwargs):
        self.replies.append(kwargs)
        return object()


async def _fake_processor(_url: str) -> str:
    return "요약"


if __name__ == "__main__":
    unittest.main()
