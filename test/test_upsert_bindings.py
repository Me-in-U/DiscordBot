import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from util import db
from util.guild.channel_settings import set_channel
from util.music.favorites import upsert_music_favorite
from util.codex_resets.notification_state import CodexResetNotificationState, save_codex_reset_notification_state
from util.codex_resets.tibo import _save_state
from util.earthquake.state import save_earthquake_alert_state, save_emsc_alert_state
from util.maplestory.events import _save_maplestory_notice_state


class UpsertBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_and_update_bind_same_value_without_deprecated_values_function(self):
        cases = [
            ('util.db.execute_query', db.upsert_guild, (1, '길드'), 1),
            ('util.db.execute_query', db.upsert_user, (2, '사용자'), 1),
            ('util.guild.channel_settings.execute_query', set_channel, (1, 'music', 3), 2),
            ('util.codex_resets.notification_state.execute_query', save_codex_reset_notification_state,
             (1, CodexResetNotificationState()), 1),
            ('util.codex_resets.tibo.execute_query', _save_state, (1, 3, {}, {}), 1),
            ('util.earthquake.state.execute_query', save_earthquake_alert_state,
             (1, SimpleNamespace(channel_id=3, records=[])), 1),
            ('util.earthquake.state.execute_query', save_emsc_alert_state,
             (1, SimpleNamespace(channel_id=3, records=[])), 1),
            ('util.db.execute_query', _save_maplestory_notice_state, ({'guilds': {}},), 1),
        ]
        for target, function, args, insert_index in cases:
            with self.subTest(function=function.__name__), patch(target, new_callable=AsyncMock) as execute:
                await function(*args)
                query, bindings = execute.await_args.args
                self.assertEqual(query.count('%s'), len(bindings))
                self.assertEqual(bindings[insert_index], bindings[-1])
                self.assertNotRegex(query, r'VALUES\([a-z_]+\)')

    async def test_favorite_overwrite_binds_every_saved_field(self):
        with patch('util.music.favorites.execute_query', new_callable=AsyncMock) as execute:
            await upsert_music_favorite(guild_id=1, slot=2, title='곡',
                url='https://youtu.be/example', duration=180, uploader='채널',
                thumbnail='https://example.com/thumb.png', updated_by=3)
        query, bindings = execute.await_args.args
        self.assertEqual(query.count('%s'), len(bindings))
        self.assertEqual(bindings[2:8], bindings[8:14])
        self.assertNotRegex(query, r'VALUES\([a-z_]+\)')
