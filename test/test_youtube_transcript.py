import tempfile
import unittest
from pathlib import Path

from func.youtube_transcript import read_subtitles_file, remove_unnecessary_line_breaks


class YouTubeTranscriptTests(unittest.TestCase):
    def test_read_subtitles_file_removes_vtt_noise_and_deduplicates_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle_path = Path(temp_dir) / "youtube_subtitles.ko.vtt"
            subtitle_path.write_text(
                "\n".join(
                    [
                        "WEBVTT",
                        "00:00:01.000 --> 00:00:02.000",
                        "<c>첫 문장입니다.</c>",
                        "<00:00:02.100>둘째 문장입니다.",
                        "둘째 문장입니다.",
                    ]
                ),
                encoding="utf-8",
            )

            transcript = read_subtitles_file(str(subtitle_path))

        self.assertEqual(transcript, "첫 문장입니다. 둘째 문장입니다.")

    def test_remove_unnecessary_line_breaks_groups_korean_sentence_endings(self):
        self.assertEqual(
            remove_unnecessary_line_breaks("첫 문장입니다\n둘째 문장입니다"),
            "첫 문장입니다\n둘째 문장입니다",
        )


if __name__ == "__main__":
    unittest.main()
