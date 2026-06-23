import unittest

from util.presence_status import (
    build_presence_activity_name,
    count_cached_user_messages,
)


class PresenceStatusTests(unittest.TestCase):
    def test_counts_only_list_messages_in_guild_user_cache(self):
        user_messages = {
            1: {
                10: ["a", "b"],
                20: [],
                30: ("not", "a", "list"),
            },
            2: {
                40: ["c"],
            },
            3: ["not-a-guild-map"],
        }

        self.assertEqual(count_cached_user_messages(user_messages), 3)

    def test_builds_presence_activity_name_with_comma_separator(self):
        user_messages = {
            1: {
                10: [object()] * 1000,
                20: [object()] * 234,
            },
        }

        self.assertEqual(
            build_presence_activity_name(user_messages),
            "/도움 | 1,234개의 채팅 메시지 보관",
        )

    def test_builds_zero_count_presence_activity_name(self):
        self.assertEqual(
            build_presence_activity_name({}),
            "/도움 | 0개의 채팅 메시지 보관",
        )


if __name__ == "__main__":
    unittest.main()
