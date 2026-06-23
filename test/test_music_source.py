import unittest


class MusicSourceTests(unittest.TestCase):
    def test_build_ffmpeg_options_adds_seek_and_input_headers_without_mutating_base(self):
        from util.music_source import build_ffmpeg_options

        base_options = {
            "before_options": "-reconnect 1",
            "options": "-vn",
        }

        options = build_ffmpeg_options(
            base_options=base_options,
            headers={"User-Agent": "agent", "Accept-Language": "ko"},
            start_time=37,
            header_target="before_options",
        )

        self.assertEqual(base_options["before_options"], "-reconnect 1")
        self.assertEqual(base_options["options"], "-vn")
        self.assertEqual(
            options["before_options"],
            '-headers "User-Agent: agent\r\nAccept-Language: ko\r\n" -reconnect 1',
        )
        self.assertEqual(options["options"], "-ss 37 -vn")

    def test_build_ffmpeg_options_can_place_headers_in_output_options_for_fallback(self):
        from util.music_source import build_ffmpeg_options

        options = build_ffmpeg_options(
            base_options={"before_options": "-reconnect 1", "options": "-vn"},
            headers={"User-Agent": "agent"},
            start_time=0,
            header_target="options",
        )

        self.assertEqual(options["before_options"], "-reconnect 1")
        self.assertEqual(
            options["options"],
            '-vn -headers "User-Agent: agent\r\n"',
        )

    def test_music_source_exports_ytdl_source_and_shared_extractors(self):
        from util.music_source import (
            YTDLSource,
            info_ytdl,
            search_ytdl,
        )

        self.assertTrue(hasattr(YTDLSource, "from_url"))
        self.assertTrue(hasattr(search_ytdl, "extract_info"))
        self.assertTrue(hasattr(info_ytdl, "extract_info"))


if __name__ == "__main__":
    unittest.main()
