import json
import os
import unittest

os.environ.setdefault("OPENAI_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from func.youtube_summary import (  # noqa: E402
    YOUTUBE_POST_KIND,
    YOUTUBE_VIDEO_KIND,
    build_youtube_post_summary_input,
    extract_youtube_links,
    extract_youtube_link,
    find_latest_youtube_link_in_messages,
    find_recent_youtube_links_in_messages,
    get_youtube_link_kind,
    parse_youtube_post_html,
)


def _build_post_html() -> str:
    post_data = {
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [
                    {
                        "tabRenderer": {
                            "content": {
                                "sectionListRenderer": {
                                    "contents": [
                                        {
                                            "itemSectionRenderer": {
                                                "contents": [
                                                    {
                                                        "backstagePostThreadRenderer": {
                                                            "post": {
                                                                "backstagePostRenderer": {
                                                                    "postId": "UgkxTestPost",
                                                                    "authorText": {
                                                                        "runs": [
                                                                            {"text": "테스트작성자"}
                                                                        ]
                                                                    },
                                                                    "contentText": {
                                                                        "runs": [
                                                                            {
                                                                                "text": "첫 문장입니다.\n둘째 문장입니다."
                                                                            }
                                                                        ]
                                                                    },
                                                                    "publishedTimeText": {
                                                                        "runs": [
                                                                            {"text": "1시간 전"}
                                                                        ]
                                                                    },
                                                                    "voteCount": {
                                                                        "simpleText": "1.2천"
                                                                    },
                                                                    "backstageAttachment": {
                                                                        "backstageImageRenderer": {
                                                                            "image": {
                                                                                "thumbnails": [
                                                                                    {
                                                                                        "url": "//i.ytimg.com/vi/test/default.jpg",
                                                                                        "width": 120,
                                                                                        "height": 90,
                                                                                    },
                                                                                    {
                                                                                        "url": "//i.ytimg.com/vi/test/maxres.jpg",
                                                                                        "width": 1280,
                                                                                        "height": 720,
                                                                                    },
                                                                                ]
                                                                            }
                                                                        }
                                                                    },
                                                                }
                                                            }
                                                        }
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ]
            }
        }
    }
    return (
        "<html><head></head><body><script>var ytInitialData = "
        f"{json.dumps(post_data, ensure_ascii=False)};"
        "</script></body></html>"
    )


class YouTubePostSummaryTests(unittest.TestCase):
    def test_finds_latest_youtube_link_from_recent_messages(self):
        class DummyMessage:
            def __init__(self, content: str):
                self.content = content

        latest_link = find_latest_youtube_link_in_messages(
            [
                DummyMessage("잡담"),
                DummyMessage("https://youtu.be/dQw4w9WgXcQ"),
                DummyMessage("https://www.youtube.com/watch?v=oldvideo"),
            ]
        )

        self.assertEqual(
            latest_link,
            ("https://youtu.be/dQw4w9WgXcQ", YOUTUBE_VIDEO_KIND),
        )

    def test_extracts_post_link_without_truncating(self):
        text = "요약해줘 http://youtube.com/post/UgkxPKcqyh9pHXg0oezn8QHB7gsESwj-NRTQ"
        self.assertEqual(
            extract_youtube_link(text),
            "https://youtube.com/post/UgkxPKcqyh9pHXg0oezn8QHB7gsESwj-NRTQ",
        )
        self.assertEqual(
            get_youtube_link_kind(
                "http://youtube.com/post/UgkxPKcqyh9pHXg0oezn8QHB7gsESwj-NRTQ"
            ),
            YOUTUBE_POST_KIND,
        )

    def test_keeps_video_link_detection(self):
        self.assertEqual(
            get_youtube_link_kind("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            YOUTUBE_VIDEO_KIND,
        )

    def test_extracts_multiple_youtube_links_from_single_message(self):
        text = (
            "첫 번째 https://youtu.be/dQw4w9WgXcQ "
            "두 번째 https://www.youtube.com/watch?v=oHg5SJYRHA0"
        )
        self.assertEqual(
            extract_youtube_links(text),
            [
                "https://youtu.be/dQw4w9WgXcQ",
                "https://www.youtube.com/watch?v=oHg5SJYRHA0",
            ],
        )

    def test_finds_recent_youtube_links_without_duplicates(self):
        class DummyMessage:
            def __init__(self, content: str):
                self.content = content

        recent_links = find_recent_youtube_links_in_messages(
            [
                DummyMessage(
                    "최신 링크 https://youtu.be/newvideo https://youtu.be/anothernew"
                ),
                DummyMessage("중복 링크 https://youtu.be/newvideo"),
                DummyMessage("게시물 https://youtube.com/post/UgkxTestPost"),
                DummyMessage("예전 링크 https://www.youtube.com/watch?v=oldvideo"),
            ],
            max_links=3,
        )

        self.assertEqual(
            recent_links,
            [
                ("https://youtu.be/newvideo", YOUTUBE_VIDEO_KIND),
                ("https://youtu.be/anothernew", YOUTUBE_VIDEO_KIND),
                ("https://youtube.com/post/UgkxTestPost", YOUTUBE_POST_KIND),
            ],
        )

    def test_parses_youtube_post_html(self):
        post_info = parse_youtube_post_html(
            _build_post_html(), "https://youtube.com/post/UgkxTestPost"
        )

        self.assertEqual(post_info.post_id, "UgkxTestPost")
        self.assertEqual(post_info.author, "테스트작성자")
        self.assertEqual(post_info.published_time, "1시간 전")
        self.assertEqual(post_info.like_count, "1.2천")
        self.assertIn("첫 문장입니다.", post_info.text)
        self.assertEqual(
            post_info.attachment_urls,
            ["https://i.ytimg.com/vi/test/maxres.jpg"],
        )

        summary_input = build_youtube_post_summary_input(post_info)
        self.assertIn("게시물 링크: https://youtube.com/post/UgkxTestPost", summary_input)
        self.assertIn("[첨부 이미지 수] 1", summary_input)


if __name__ == "__main__":
    unittest.main()
