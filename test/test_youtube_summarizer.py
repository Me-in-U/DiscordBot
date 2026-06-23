import asyncio
import unittest
from unittest.mock import patch

from func.youtube_post import YouTubePostInfo
from func.youtube_summarizer import (
    summarize_comments_with_gpt,
    summarize_text_with_gpt,
    summarize_youtube_post_with_gpt,
)


class YouTubeSummarizerTests(unittest.TestCase):
    def test_summarize_comments_joins_comments_for_prompt_payload(self):
        with patch("func.youtube_summarizer.build_prompt", return_value={"p": "comments"}) as build_prompt:
            with patch("func.youtube_summarizer.custom_prompt_model", return_value="댓글 요약"):
                result = asyncio.run(summarize_comments_with_gpt(["첫 댓글", "둘째 댓글"]))

        self.assertEqual(result, "댓글 요약")
        self.assertEqual(build_prompt.call_args.args[2]["comments_text"], "첫 댓글\n둘째 댓글")

    def test_summarize_text_uses_transcript_payload(self):
        with patch("func.youtube_summarizer.build_prompt", return_value={"p": "video"}) as build_prompt:
            with patch("func.youtube_summarizer.custom_prompt_model", return_value="영상 요약"):
                result = asyncio.run(summarize_text_with_gpt("자막 텍스트"))

        self.assertEqual(result, "영상 요약")
        self.assertEqual(build_prompt.call_args.args[2]["youtube_text"], "자막 텍스트")

    def test_summarize_post_uses_post_input_with_generate_text_model(self):
        post = YouTubePostInfo(
            post_id="post-id",
            url="https://youtube.com/post/post-id",
            text="본문",
        )
        with patch("func.youtube_summarizer.generate_text_model", return_value="게시물 요약") as generate:
            result = asyncio.run(summarize_youtube_post_with_gpt(post))

        self.assertEqual(result, "게시물 요약")
        self.assertIn("게시물 링크: https://youtube.com/post/post-id", generate.call_args.args[0])
        self.assertEqual(generate.call_args.args[2], "gpt-5.4-mini")


if __name__ == "__main__":
    unittest.main()
