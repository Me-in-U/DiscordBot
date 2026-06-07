import json
import unittest

from util.youtube_community import (
    build_youtube_community_post_url,
    build_youtube_community_posts_url,
    find_new_youtube_community_posts,
    parse_youtube_community_posts_html,
    trim_notified_community_post_ids,
)


def _build_posts_html() -> str:
    initial_data = {
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [
                    {
                        "tabRenderer": {
                            "content": {
                                "richGridRenderer": {
                                    "contents": [
                                        {
                                            "richItemRenderer": {
                                                "content": {
                                                    "backstagePostRenderer": {
                                                        "postId": "UgkxFirstPost",
                                                        "authorText": {
                                                            "runs": [{"text": "테스트 채널"}]
                                                        },
                                                        "publishedTimeText": {
                                                            "runs": [{"text": "2일 전"}]
                                                        },
                                                        "contentText": {
                                                            "runs": [
                                                                {
                                                                    "text": "첫 번째 게시물입니다.\n방송 일정 안내"
                                                                }
                                                            ]
                                                        },
                                                        "backstageAttachment": {
                                                            "backstageImageRenderer": {
                                                                "image": {
                                                                    "thumbnails": [
                                                                        {
                                                                            "url": "//i.ytimg.com/post/small.jpg",
                                                                            "width": 120,
                                                                            "height": 90,
                                                                        },
                                                                        {
                                                                            "url": "//i.ytimg.com/post/large.jpg",
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
                                        },
                                        {
                                            "richItemRenderer": {
                                                "content": {
                                                    "backstagePostRenderer": {
                                                        "postId": "UgkxSecondPost",
                                                        "authorText": {
                                                            "simpleText": "테스트 채널"
                                                        },
                                                        "publishedTimeText": {
                                                            "simpleText": "1주 전"
                                                        },
                                                        "contentText": {
                                                            "simpleText": "두 번째 게시물입니다."
                                                        },
                                                    }
                                                }
                                            }
                                        },
                                        {
                                            "richItemRenderer": {
                                                "content": {
                                                    "backstagePostRenderer": {
                                                        "postId": "UgkxFirstPost",
                                                        "contentText": {
                                                            "simpleText": "중복 게시물입니다."
                                                        },
                                                    }
                                                }
                                            }
                                        },
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
        f"{json.dumps(initial_data, ensure_ascii=False)};"
        "</script></body></html>"
    )


class YouTubeCommunityTests(unittest.TestCase):
    def test_builds_channel_posts_and_direct_post_urls(self):
        self.assertEqual(
            build_youtube_community_posts_url("UC1234567890123456789012"),
            "https://www.youtube.com/channel/UC1234567890123456789012/posts",
        )
        self.assertEqual(
            build_youtube_community_post_url("UgkxFirstPost"),
            "https://youtube.com/post/UgkxFirstPost",
        )

    def test_parses_unique_posts_from_initial_data_in_display_order(self):
        posts = parse_youtube_community_posts_html(_build_posts_html())

        self.assertEqual([post.post_id for post in posts], ["UgkxFirstPost", "UgkxSecondPost"])
        self.assertEqual(posts[0].author, "테스트 채널")
        self.assertEqual(posts[0].published_time, "2일 전")
        self.assertEqual(posts[0].text, "첫 번째 게시물입니다.\n방송 일정 안내")
        self.assertEqual(
            posts[0].attachment_urls,
            ["https://i.ytimg.com/post/large.jpg"],
        )
        self.assertEqual(posts[0].url, "https://youtube.com/post/UgkxFirstPost")

    def test_finds_only_posts_not_already_notified(self):
        posts = parse_youtube_community_posts_html(_build_posts_html())

        new_posts = find_new_youtube_community_posts(
            posts,
            notified_post_ids=["UgkxFirstPost"],
        )

        self.assertEqual([post.post_id for post in new_posts], ["UgkxSecondPost"])

    def test_trims_notified_ids_to_recent_limit(self):
        notified_ids = [f"post-{index}" for index in range(35)]

        self.assertEqual(
            trim_notified_community_post_ids(notified_ids, limit=30),
            [f"post-{index}" for index in range(5, 35)],
        )


if __name__ == "__main__":
    unittest.main()
