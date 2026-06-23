import unittest


class MusicPanelStoreTests(unittest.IsolatedAsyncioTestCase):
    def test_rows_to_music_panel_ids_normalizes_keys_and_values(self):
        from util.music_panel_store import rows_to_music_panel_ids

        rows = [
            {"guild_id": 123, "message_id": "456"},
            {"guild_id": "789", "message_id": 111},
        ]

        self.assertEqual(rows_to_music_panel_ids(rows), {"123": 456, "789": 111})

    async def test_load_music_panel_ids_uses_panel_messages_query(self):
        from util.music_panel_store import load_music_panel_ids

        calls: list[str] = []

        async def fetch_all(query):
            calls.append(query)
            return [{"guild_id": 1, "message_id": 2}]

        result = await load_music_panel_ids(fetch_all=fetch_all)

        self.assertEqual(result, {"1": 2})
        self.assertEqual(calls, ["SELECT guild_id, message_id FROM panel_messages"])

    async def test_save_music_panel_id_updates_cache_and_persists_upsert(self):
        from util.music_panel_store import save_music_panel_id

        cache = {}
        calls = []

        async def execute_query(query, args):
            calls.append((query, args))

        await save_music_panel_id(cache, "123", "456", execute_query=execute_query)

        self.assertEqual(cache, {"123": 456})
        self.assertEqual(calls[0][1], (123, 456, 456))
        self.assertIn("ON DUPLICATE KEY UPDATE message_id = %s", calls[0][0])

    async def test_delete_music_panel_id_updates_cache_and_persists_delete(self):
        from util.music_panel_store import delete_music_panel_id

        cache = {"123": 456}
        calls = []

        async def execute_query(query, args):
            calls.append((query, args))

        await delete_music_panel_id(cache, "123", execute_query=execute_query)

        self.assertEqual(cache, {})
        self.assertEqual(calls, [("DELETE FROM panel_messages WHERE guild_id = %s", (123,))])
