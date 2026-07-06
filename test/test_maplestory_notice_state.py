import unittest
from pathlib import Path

from util.maplestory.events import MapleStoryNotice
from util.maplestory.notice_state import (
    build_maplestory_notice_fingerprint,
    get_maplestory_notice_maintenance_status,
    get_latest_maplestory_notice_message_record,
    get_maplestory_notice_pre_completion_message_records,
    find_maplestory_notice_updates_with_state,
    find_maplestory_notice_updates,
    maplestory_notice_state_from_notices,
    remember_maplestory_notice_in_state,
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

    def test_maintenance_notice_status_detects_pre_completion_and_completion_titles(self):
        cases = [
            ("[점검예정] 6/25(목) 챌린저스 월드 채널 점검", "scheduled"),
            ("[점검중] 6/25(목) 챌린저스 월드 채널 점검", "in_progress"),
            ("(수정) 6/25(목) 연장 점검 안내", "extended"),
            ("6/25(목) 연장 점검 안내", "extended"),
            ("[점검완료] 6/25(목) 챌린저스 월드 채널 점검", "completed"),
        ]

        for title, expected in cases:
            with self.subTest(title=title):
                notice = MapleStoryNotice(
                    notice_id="149500",
                    category="[점검]",
                    title=title,
                    url="https://maplestory.nexon.com/News/Notice/149500",
                )

                self.assertEqual(
                    get_maplestory_notice_maintenance_status(notice),
                    expected,
                )

    def test_notice_state_tracks_previous_pre_completion_message_records(self):
        scheduled = MapleStoryNotice(
            notice_id="149500",
            category="[점검]",
            title="[점검예정] 6/25(목) 챌린저스 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149500",
            summary="오전 11시 50분부터 점검합니다.",
        )
        completed = MapleStoryNotice(
            notice_id="149500",
            category="[점검]",
            title="[점검완료] 6/25(목) 챌린저스 월드 채널 점검",
            url="https://maplestory.nexon.com/News/Notice/149500",
            summary="점검이 완료되었습니다.",
        )
        state = maplestory_notice_state_from_notices([scheduled])

        remember_maplestory_notice_in_state(
            state,
            scheduled,
            channel_id=1234,
            message_id=111,
        )

        records = get_maplestory_notice_pre_completion_message_records(
            state,
            completed,
            channel_id=1234,
        )

        self.assertEqual([record["messageId"] for record in records], [111])

    def test_notice_state_finds_latest_message_record_for_same_notice_and_channel(self):
        notice = MapleStoryNotice(
            notice_id="149600",
            category="[공지]",
            title="6/30(화) 테스트 공지",
            url="https://maplestory.nexon.com/News/Notice/149600",
            summary="첫 공지입니다.",
        )
        state = maplestory_notice_state_from_notices([notice])
        remember_maplestory_notice_in_state(
            state,
            notice,
            channel_id=1234,
            message_id=111,
        )
        remember_maplestory_notice_in_state(
            state,
            notice,
            channel_id=5678,
            message_id=222,
        )
        remember_maplestory_notice_in_state(
            state,
            notice,
            channel_id=1234,
            message_id=333,
        )

        record = get_latest_maplestory_notice_message_record(
            state,
            notice,
            channel_id=1234,
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["messageId"], 333)


if __name__ == "__main__":
    unittest.main()
