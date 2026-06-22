import unittest
from pathlib import Path

from util.maplestory_events import MapleStoryNotice
from util.maplestory.notice_state import (
    find_maplestory_notice_updates,
    maplestory_notice_state_from_notices,
)


MAPLESTORY_NOTICE_STATE_PATH = Path("util/maplestory/notice_state.py")
LEGACY_MAPLESTORY_NOTICE_STATE_PATH = Path("util/maplestory_notice_state.py")


class MapleStoryNoticeStateTests(unittest.TestCase):
    def test_maplestory_notice_state_lives_under_maplestory_package(self):
        self.assertTrue(MAPLESTORY_NOTICE_STATE_PATH.exists())
        self.assertFalse(LEGACY_MAPLESTORY_NOTICE_STATE_PATH.exists())

    def test_notice_state_helpers_are_available_from_state_module(self):
        original = MapleStoryNotice(
            notice_id="149371",
            category="[점검]",
            title="6/22(월) 서버점검",
            url="https://maplestory.nexon.com/News/Notice/149371",
            summary="오후 4시부터 점검을 진행합니다.",
        )
        changed = MapleStoryNotice(
            notice_id="149371",
            category="[점검]",
            title="[점검완료] 6/22(월) 서버점검",
            url="https://maplestory.nexon.com/News/Notice/149371",
            summary="오후 4시 55분 점검이 완료되었습니다.",
        )

        state = maplestory_notice_state_from_notices([original])
        updates = find_maplestory_notice_updates([changed], state)

        self.assertEqual(updates, [changed])


if __name__ == "__main__":
    unittest.main()
