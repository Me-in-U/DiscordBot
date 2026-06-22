import unittest
from pathlib import Path

from util.celebration.announcements import CelebrationUpdateResult


CELEBRATION_ANNOUNCEMENTS_PATH = Path("util/celebration/announcements.py")
LEGACY_CELEBRATION_PATH = Path("util/celebration.py")


class CelebrationHelperTests(unittest.TestCase):
    def test_celebration_helper_lives_under_celebration_package(self):
        self.assertTrue(CELEBRATION_ANNOUNCEMENTS_PATH.exists())
        self.assertFalse(LEGACY_CELEBRATION_PATH.exists())

    def test_update_result_to_dict_omits_empty_optional_fields(self):
        result = CelebrationUpdateResult(
            guild_id=1,
            channel_id=2,
            message_id=3,
            action="edited",
        )

        self.assertEqual(
            result.to_dict(),
            {
                "guild_id": 1,
                "status": "ok",
                "channel_id": 2,
                "message_id": 3,
                "action": "edited",
            },
        )


if __name__ == "__main__":
    unittest.main()
