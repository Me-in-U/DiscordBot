import unittest
from pathlib import Path

from util.maplestory.events import MapleStoryNotice
from util.maplestory.notice_state import (
    build_maplestory_notice_fingerprint,
    find_maplestory_notice_updates_with_state,
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

    def test_missing_body_fingerprint_is_migrated_without_resending_notice(self):
        notice = MapleStoryNotice(
            notice_id="149382",
            category="[점검]",
            title="[점검완료] 6/23(화) 전체 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149382",
            summary="오후 5시 45분부터 오후 6시 45분까지 점검합니다.",
            body_text=(
                "[작업 일시] 2026년 6월 23일 오후 5시 45분 ~ 오후 6시 45분 "
                "[작업 대상] 모든 메이플스토리 월드 "
                "[작업 내역] 서버 안정화"
            ),
        )
        legacy_state = {
            "notices": {
                "149382": {
                    "fingerprint": build_maplestory_notice_fingerprint(notice),
                    "title": notice.title,
                    "category": notice.category,
                }
            },
            "recentNoticeIds": ["149382"],
        }

        updates, migrated_state, migrated = find_maplestory_notice_updates_with_state(
            [notice],
            legacy_state,
        )

        self.assertEqual(updates, [])
        self.assertTrue(migrated)
        self.assertIn("bodyFingerprint", migrated_state["notices"]["149382"])


if __name__ == "__main__":
    unittest.main()
