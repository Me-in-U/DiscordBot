import json
import unittest

from func.youtube_post import build_youtube_post_summary_input, parse_youtube_post_html


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
                                                                    "postId": "UgkxParserPost",
                                                                    "authorText": {
                                                                        "runs": [
                                                                            {"text": "작성자"}
                                                                        ]
                                                                    },
                                                                    "contentText": {
                                                                        "runs": [
                                                                            {"text": "본문입니다."}
                                                                        ]
                                                                    },
                                                                    "publishedTimeText": {
                                                                        "simpleText": "방금 전"
                                                                    },
                                                                    "voteCount": {
                                                                        "accessibility": {
                                                                            "accessibilityData": {
                                                                                "label": "좋아요 10개"
                                                                            }
                                                                        }
                                                                    },
                                                                    "backstageAttachment": {
                                                                        "backstageImageRenderer": {
                                                                            "image": {
                                                                                "thumbnails": [
                                                                                    {
                                                                                        "url": "//i.ytimg.com/vi/test/low.jpg",
                                                                                        "width": 120,
                                                                                        "height": 90,
                                                                                    },
                                                                                    {
                                                                                        "url": "//i.ytimg.com/vi/test/high.jpg",
                                                                                        "width": 640,
                                                                                        "height": 480,
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
        "<html><body><script>var ytInitialData = "
        f"{json.dumps(post_data, ensure_ascii=False)};"
        "</script></body></html>"
    )


class YouTubePostParserTests(unittest.TestCase):
    def test_parses_post_html_and_builds_summary_input_from_post_module(self):
        post = parse_youtube_post_html(
            _build_post_html(),
            "https://youtube.com/post/UgkxParserPost",
        )

        self.assertEqual(post.post_id, "UgkxParserPost")
        self.assertEqual(post.author, "작성자")
        self.assertEqual(post.published_time, "방금 전")
        self.assertEqual(post.like_count, "좋아요 10개")
        self.assertEqual(post.text, "본문입니다.")
        self.assertEqual(
            post.attachment_urls,
            ["https://i.ytimg.com/vi/test/high.jpg"],
        )

        summary_input = build_youtube_post_summary_input(post)

        self.assertIn("게시물 링크: https://youtube.com/post/UgkxParserPost", summary_input)
        self.assertIn("[첨부 이미지 수] 1", summary_input)


if __name__ == "__main__":
    unittest.main()
