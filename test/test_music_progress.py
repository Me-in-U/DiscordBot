import unittest
import warnings


class MusicProgressHelperTests(unittest.TestCase):
    def test_format_music_time_uses_mmss(self):
        from util.music_progress import format_music_time

        self.assertEqual(format_music_time(0), "00:00")
        self.assertEqual(format_music_time(83), "01:23")
        self.assertEqual(format_music_time(3605), "60:05")

    def test_make_progress_bar_clamps_elapsed_to_valid_range(self):
        from util.music_progress import make_progress_bar

        self.assertEqual(make_progress_bar(-5, 100, length=5), ("▱" * 5, 0))
        self.assertEqual(make_progress_bar(50, 100, length=5), ("▰▰▱▱▱", 2))
        self.assertEqual(make_progress_bar(150, 100, length=5), ("▰" * 5, 5))

    def test_make_timeline_line_uses_same_filled_count_as_progress_bar(self):
        from util.music_progress import H_BAR, make_timeline_line

        self.assertEqual(
            make_timeline_line(30, 120, length=4),
            f"{H_BAR}00:30{H_BAR * 3} 02:00 (25%)",
        )

    def test_legacy_music_cog_delegates_to_progress_helpers(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from cogs.music import MusicCog
        from util.music_progress import make_progress_bar, make_timeline_line

        cog = MusicCog.__new__(MusicCog)

        self.assertEqual(cog.make_progress_bar(50, 100, 5), make_progress_bar(50, 100, 5))
        self.assertEqual(
            cog.make_timeline_line(30, 120, 4),
            make_timeline_line(30, 120, 4),
        )


if __name__ == "__main__":
    unittest.main()
