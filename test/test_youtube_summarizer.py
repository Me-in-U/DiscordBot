import asyncio
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from func.youtube_post import YouTubePostInfo
from func.youtube_summarizer import (
    COMMENTS_SUMMARY_PROMPT_VERSION,
    YOUTUBE_POST_SUMMARY_PROMPT_ID,
    YOUTUBE_POST_SUMMARY_PROMPT_VERSION,
    YOUTUBE_SUMMARY_PROMPT_VERSION,
    summarize_comments_with_gpt,
    summarize_text_with_gpt,
    summarize_youtube_post_with_gpt,
)


class YouTubeSummarizerTests(unittest.TestCase):
    def test_uses_published_summary_prompt_versions(self):
        self.assertEqual(COMMENTS_SUMMARY_PROMPT_VERSION, "13")
        self.assertEqual(YOUTUBE_SUMMARY_PROMPT_VERSION, "11")

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

    def test_summarize_post_uses_stored_prompt_and_user_input(self):
        post = YouTubePostInfo(
            post_id="post-id",
            url="https://youtube.com/post/post-id",
            text="본문",
        )
        with patch("func.youtube_summarizer.custom_prompt_model", return_value="게시물 요약") as generate:
            result = asyncio.run(summarize_youtube_post_with_gpt(post))

        self.assertEqual(result, "게시물 요약")
        self.assertIn("게시물 링크: https://youtube.com/post/post-id", generate.call_args.kwargs["image_content"][0]["content"][0]["text"])
        self.assertEqual(generate.call_args.kwargs["prompt"], {
            "id": YOUTUBE_POST_SUMMARY_PROMPT_ID, "version": YOUTUBE_POST_SUMMARY_PROMPT_VERSION,
        })
        self.assertNotIn("instructions", generate.call_args.kwargs)
        self.assertEqual(generate.call_args.kwargs["max_output_tokens"], 400)


if __name__ == "__main__":
    unittest.main()
