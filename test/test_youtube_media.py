import unittest

from func.youtube_media import build_headers_str


class YouTubeMediaTests(unittest.TestCase):
    def test_build_headers_str_uses_crlf_between_headers(self):
        self.assertEqual(
            build_headers_str({"User-Agent": "Bot", "Accept": "text/html"}),
            "User-Agent: Bot\r\nAccept: text/html\r\n",
        )


if __name__ == "__main__":
    unittest.main()
