import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.music import MusicCog
from util.music.embeds import PANEL_TITLE
from util.music.queue import QueuedTrack


class VoiceClient:
    def __init__(self):
        self.channel = SimpleNamespace(members=[object(), object()])
        self.active = False
        self.callbacks = []
        self.played = []

    def is_playing(self):
        return self.active

    def is_paused(self):
        return False

    def play(self, source, *, after):
        if self.active:
            raise AssertionError('Existing audio was interrupted')
        self.active = True
        self.played.append(source)
        self.callbacks.append(after)

    def stop(self):
        self.active = False

    async def disconnect(self):
        self.stop()


def player(title):
    return SimpleNamespace(
        title=title, source=title, webpage_url='https://example.com/' + title,
        requester=None, data={'duration': 180},
    )


class MusicLifecycleRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.voice = VoiceClient()
        self.guild = SimpleNamespace(id=1, voice_client=self.voice)
        self.cog = MusicCog(SimpleNamespace(
            loop=asyncio.get_running_loop(), get_guild=lambda guild_id: self.guild,
        ))
        self.state = self.cog._get_state(1)
        self.cog._build_control_view = AsyncMock(return_value='controls')
        self.cog._build_helper_view = AsyncMock(return_value='helper')
        self.cog._make_playing_embed = MagicMock(return_value='playing')
        self.cog._make_default_embed = MagicMock(return_value='idle')
        self.cog._edit_msg = AsyncMock()
        self.cog._restart_updater = AsyncMock()
        self.cog._send_auto_delete = AsyncMock()
        self.cog._schedule_idle_disconnect = MagicMock()

    async def asyncTearDown(self):
        tasks = list(self.cog._bg_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def interaction(self):
        response = SimpleNamespace(done=False)
        async def defer(**kwargs):
            response.done = True
        response.defer = AsyncMock(side_effect=defer)
        response.is_done = lambda: response.done
        return SimpleNamespace(
            guild=self.guild, response=response,
            user=SimpleNamespace(id=2, voice=SimpleNamespace(channel=self.voice.channel)),
        )

    async def flush_callbacks(self):
        await asyncio.sleep(0)
        await asyncio.gather(*list(self.cog._bg_tasks))

    async def test_late_old_callback_after_seek_keeps_new_track_and_queue(self):
        old = player('old')
        self.state.player = old
        self.state.queue.append(QueuedTrack(url='https://example.com/queued'))
        self.cog._vc_play(guild_id=1, source=old.source)
        old_callback = self.voice.callbacks[0]
        new = player('seek')
        with patch('cogs.music.controls.prepare_music_player', AsyncMock(return_value=new)):
            await self.cog._seek(self.interaction(), 30)
        old_callback(None)
        await self.flush_callbacks()
        self.assertIs(self.state.player, new)
        self.assertEqual(len(self.state.queue), 1)
        self.assertEqual(self.voice.played, ['old', 'seek'])
        self.cog._schedule_idle_disconnect.assert_not_called()

    async def test_callback_waiting_for_lock_checks_generation_after_acquiring(self):
        self.state.player = player('old')
        self.state.playback_generation = 1
        self.state.queue.append(QueuedTrack(url='queued'))
        async with self.cog._music_operation(1):
            callback = asyncio.create_task(self.cog._on_song_end(1, generation=1))
            await asyncio.sleep(0)
            self.assertFalse(callback.done())
            self.state.playback_generation = 2
            new = player('new')
            self.state.player = new
        await callback
        self.assertIs(self.state.player, new)
        self.assertEqual(len(self.state.queue), 1)
        self.cog._schedule_idle_disconnect.assert_not_called()

    async def test_current_track_end_resets_panel_and_schedules_idle_disconnect(self):
        self.state.player = player('last')
        self.cog._vc_play(guild_id=1, source='last')
        self.voice.stop()
        self.voice.callbacks[0](None)
        await self.flush_callbacks()
        self.assertIsNone(self.state.player)
        self.cog._edit_msg.assert_awaited_with(self.state, 'idle', 'helper')
        self.cog._schedule_idle_disconnect.assert_called_once_with(1)

    async def test_other_guild_operations_do_not_wait_for_first_guild(self):
        entered = asyncio.Event()
        async def other_guild():
            async with self.cog._music_operation(2):
                entered.set()
        async with self.cog._music_operation(1):
            task = asyncio.create_task(other_guild())
            await asyncio.wait_for(entered.wait(), 1)
        await task

    async def test_late_callback_after_replacement_is_ignored(self):
        self.state.player = player('old')
        self.cog._vc_play(guild_id=1, source='old')
        callback = self.voice.callbacks[0]
        new = player('favorite')
        self.cog._prepare_play_url_now_player = AsyncMock(return_value=new)
        await self.cog._play_url_now(self.interaction(), new.webpage_url)
        callback(None)
        await self.flush_callbacks()
        self.assertIs(self.state.player, new)
        self.assertFalse(self.state.is_seeking)
        self.cog._schedule_idle_disconnect.assert_not_called()

    async def test_duplicate_callback_advances_queue_only_once(self):
        self.state.player = player('old')
        self.state.queue.extend([QueuedTrack(url='one'), QueuedTrack(url='two')])
        self.cog._vc_play(guild_id=1, source='old')
        self.voice.stop()
        callback = self.voice.callbacks[0]
        with patch('cogs.music.playback.prepare_music_player', AsyncMock(return_value=player('one'))):
            callback(None)
            callback(None)
            await self.flush_callbacks()
        self.assertEqual(self.voice.played, ['old', 'one'])
        self.assertEqual([track.url for track in self.state.queue], ['two'])

    async def test_concurrent_url_requests_play_first_and_queue_second(self):
        preparing = asyncio.Event()
        release = asyncio.Event()
        async def prepare(interaction, url):
            preparing.set()
            await release.wait()
            return player('first')
        self.cog._prepare_music_url_immediate_player = AsyncMock(side_effect=prepare)
        first = asyncio.create_task(self.cog._play_music_url_branch(self.interaction(), 'https://example.com/first'))
        await preparing.wait()
        second_interaction = self.interaction()
        second = asyncio.create_task(self.cog._play_music_url_branch(second_interaction, 'https://example.com/second'))
        await asyncio.sleep(0)
        self.assertTrue(second_interaction.response.is_done())
        self.assertFalse(second.done())
        self.assertEqual(self.cog._prepare_music_url_immediate_player.await_count, 1)
        self.cog._fill_queue_meta = AsyncMock()
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.voice.played, ['first'])
        self.assertEqual([track.url for track in self.state.queue], ['https://example.com/second'])

    async def test_stop_during_preparation_cannot_revive_playback_after_stop(self):
        preparing, release = asyncio.Event(), asyncio.Event()
        async def prepare(interaction, url):
            preparing.set()
            await release.wait()
            return player('first')
        self.cog._prepare_music_url_immediate_player = AsyncMock(side_effect=prepare)
        play_task = asyncio.create_task(self.cog._play_music_url_branch(self.interaction(), 'https://example.com/first'))
        await preparing.wait()
        stop_task = asyncio.create_task(self.cog._stop(self.interaction()))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(play_task, stop_task)
        self.assertIsNone(self.state.player)
        self.assertFalse(self.voice.active)
        self.voice.callbacks[0](None)
        await self.flush_callbacks()
        self.assertIsNone(self.state.player)
        self.cog._schedule_idle_disconnect.assert_not_called()

    async def test_search_is_acknowledged_before_waiting_for_results(self):
        interaction = self.interaction()
        async def search(*args, **kwargs):
            self.assertTrue(interaction.response.is_done())
            return SimpleNamespace()
        self.cog._send_music_search_response = AsyncMock()
        with patch('cogs.music.queue.build_music_search_flow', AsyncMock(side_effect=search)):
            await self.cog._play_music_search_branch(interaction, 'query')
        self.cog._send_music_search_response.assert_awaited_once()

    async def test_favorite_search_is_acknowledged_before_waiting(self):
        interaction = self.interaction()
        async def search(*args, **kwargs):
            self.assertTrue(interaction.response.is_done())
            return SimpleNamespace()
        self.cog._send_music_search_response = AsyncMock()
        with patch('cogs.music.favorites.build_music_search_flow', AsyncMock(side_effect=search)):
            await self.cog._search_music_for_favorite_slot(interaction, 1, 'query')
        self.cog._send_music_search_response.assert_awaited_once()

    async def test_panel_reopen_preserves_playing_and_paused_controls(self):
        panel = SimpleNamespace(id=5, author='bot', embeds=[SimpleNamespace(title=PANEL_TITLE)])
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=panel))
        self.guild.me = 'bot'
        self.cog._resolve_music_channel = AsyncMock(return_value=channel)
        self.cog._panel_ids['1'] = 5
        self.state.player = player('playing')
        self.state.start_ts = 100
        for paused_at, expected in [(None, 30), (120, 20)]:
            with self.subTest(paused_at=paused_at):
                self.state.paused_at = paused_at
                embed = SimpleNamespace(title=PANEL_TITLE)
                self.cog._make_playing_embed.return_value = embed
                with patch('cogs.music.panel.time.time', return_value=130):
                    await self.cog._get_or_create_panel(self.guild)
                self.cog._make_playing_embed.assert_called_with(self.state.player, 1, expected)
                self.assertEqual(self.state.control_view, 'controls')
                self.cog._edit_msg.assert_awaited_with(self.state, embed, 'controls')
        self.cog._build_helper_view.assert_not_awaited()

    async def test_updater_restart_handles_task_cancelled_before_first_step(self):
        async def pending():
            await asyncio.Event().wait()
        previous = asyncio.create_task(pending())
        self.state.updater_task = previous
        self.cog._updater_loop = AsyncMock()
        from cogs.music.playback import MusicPlaybackMixin
        await asyncio.wait_for(MusicPlaybackMixin._restart_updater(self.cog, 1), 1)
        self.assertTrue(previous.cancelled())
        await asyncio.gather(*list(self.cog._bg_tasks))

    async def test_nested_search_pick_can_acquire_url_play_lock(self):
        self.cog._prepare_music_url_immediate_player = AsyncMock(return_value=player('picked'))
        await asyncio.wait_for(self.cog._play_from_search_pick(self.interaction(), {'url': 'https://example.com/picked'}), 1)
        self.assertEqual(self.voice.played, ['picked'])
        self.assertIsNone(self.state.operation_owner)

    async def test_operation_lock_is_released_on_failure(self):
        with self.assertRaises(ValueError):
            async with self.cog._music_operation(1):
                raise ValueError('failure')
        async with self.cog._music_operation(1):
            self.assertIs(self.state.operation_owner, asyncio.current_task())
        self.assertFalse(self.state.operation_lock.locked())

    async def test_failed_playback_start_cleans_source_and_resets_state(self):
        prepared = player('failed')
        prepared.source = MagicMock()
        self.cog._vc_play = MagicMock(side_effect=RuntimeError('disconnected'))
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            await self.cog._start_prepared_playback(
                guild_id=1, state=self.state, player=prepared,
                playback_start=SimpleNamespace(source=prepared.source),
            )
        prepared.source.cleanup.assert_called_once()
        self.assertIsNone(self.state.player)
        self.assertIsNone(self.state.updater_task)
        self.cog._schedule_idle_disconnect.assert_called_once_with(1)

    async def test_cancelled_playback_start_cleans_source_and_resets_state(self):
        prepared = player('cancelled')
        prepared.source = MagicMock()
        self.cog._build_control_view.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.cog._start_prepared_playback(
                guild_id=1, state=self.state, player=prepared,
                playback_start=SimpleNamespace(source=prepared.source),
            )
        prepared.source.cleanup.assert_called_once()
        self.assertIsNone(self.state.player)
        self.cog._schedule_idle_disconnect.assert_called_once_with(1)

    async def test_stop_resets_state_even_when_panel_update_fails(self):
        self.state.player = player('playing')
        self.state.queue.append(QueuedTrack(url='queued'))
        self.state.paused_at = 100
        self.cog._edit_msg.side_effect = RuntimeError('panel failed')
        with self.assertRaisesRegex(RuntimeError, 'panel failed'):
            await self.cog._stop(self.interaction())
        self.assertIsNone(self.state.player)
        self.assertIsNone(self.state.paused_at)
        self.assertFalse(self.state.queue)
        self.assertFalse(self.state.is_stopping)

    async def test_stop_resets_state_even_when_disconnect_fails(self):
        self.state.player = player('playing')
        self.voice.disconnect = AsyncMock(side_effect=OSError('disconnect failed'))
        with self.assertRaises(OSError):
            await self.cog._stop(self.interaction())
        self.assertIsNone(self.state.player)
        self.assertFalse(self.state.is_stopping)

    async def test_force_stop_resets_state_even_when_panel_update_fails(self):
        self.state.player = player('playing')
        self.cog._edit_msg.side_effect = RuntimeError('panel failed')
        with self.assertRaisesRegex(RuntimeError, 'panel failed'):
            await self.cog._force_stop(1)
        self.assertIsNone(self.state.player)
        self.assertFalse(self.state.is_stopping)

    async def test_loop_playback_error_refreshes_once_then_stops(self):
        self.state.player = player('looping')
        self.state.is_loop = True
        self.cog._vc_play(guild_id=1, source='old')
        self.voice.stop()
        refreshed = SimpleNamespace(audio_url='fresh-url')
        replay = SimpleNamespace(source='fresh-source', refreshed_player=refreshed)
        with patch('cogs.music.playback.prepare_replay_source', AsyncMock(return_value=replay)) as prepare:
            with self.assertLogs('cogs.music', level='WARNING'):
                self.voice.callbacks[0](RuntimeError('stream failed'))
                await self.flush_callbacks()
                self.assertTrue(prepare.await_args.kwargs['refresh'])
                self.assertEqual(self.state.playback_error_retries, 1)
                self.voice.stop()
                self.voice.callbacks[1](RuntimeError('stream still failed'))
                await self.flush_callbacks()
            self.assertEqual(prepare.await_count, 1)
        self.assertIsNone(self.state.player)
        self.assertFalse(self.state.is_loop)
        self.assertEqual(self.voice.played, ['old', 'fresh-source'])

    async def test_failed_preparation_schedules_idle_disconnect(self):
        self.cog._prepare_music_url_immediate_player = AsyncMock(return_value=None)
        await self.cog._play_music_url_branch(self.interaction(), 'https://example.com/broken')
        self.cog._schedule_idle_disconnect.assert_called_once_with(1)
        self.assertIsNone(self.state.player)

    async def test_failed_favorite_replacement_keeps_current_playback(self):
        original = player('current')
        self.state.player = original
        self.cog._prepare_play_url_now_player = AsyncMock(return_value=None)
        await self.cog._play_url_now(self.interaction(), 'https://example.com/broken')
        self.assertIs(self.state.player, original)
        self.cog._schedule_idle_disconnect.assert_not_called()

    async def test_favorite_play_defers_before_database_lookup(self):
        interaction = self.interaction()
        self.cog._send_ephemeral_response = AsyncMock()
        async def lookup(*args):
            self.assertTrue(interaction.response.is_done())
            return None
        with patch('cogs.music.favorites.get_music_favorite', AsyncMock(side_effect=lookup)):
            await self.cog._play_music_favorite(interaction, 1)
        self.cog._send_ephemeral_response.assert_awaited_once()

    async def test_favorite_database_failure_reports_error_without_starting_playback(self):
        import aiomysql
        interaction = self.interaction()
        self.cog._send_ephemeral_response = AsyncMock()
        self.cog._play_url_now = AsyncMock()
        with patch('cogs.music.favorites.get_music_favorite', AsyncMock(side_effect=aiomysql.Error('DB down'))):
            with self.assertLogs('cogs.music', level='WARNING'):
                await self.cog._play_music_favorite(interaction, 1)
        self.assertTrue(interaction.response.is_done())
        self.cog._send_ephemeral_response.assert_awaited_once()
        self.cog._play_url_now.assert_not_awaited()

    async def test_favorite_refresh_waits_for_stop_and_reads_latest_state(self):
        self.state.control_msg = object()
        self.state.control_channel = object()
        self.state.player = player('old')
        async with self.cog._music_operation(1):
            refresh = asyncio.create_task(self.cog._refresh_music_panel_for_favorites(1))
            await asyncio.sleep(0)
            self.cog._edit_msg.assert_not_awaited()
            self.state.player = None
        await refresh
        self.cog._edit_msg.assert_awaited_with(self.state, 'idle', 'helper')
        self.cog._make_playing_embed.assert_not_called()

    async def test_updater_waits_for_state_lock_and_does_not_send_stale_panel(self):
        from cogs.music.playback import MusicPlaybackMixin
        self.state.player = player('old')
        async with self.cog._music_operation(1):
            updater = asyncio.create_task(MusicPlaybackMixin._updater_loop(self.cog, 1))
            await asyncio.sleep(0)
            self.cog._edit_msg.assert_not_awaited()
            self.state.player = None
        await updater
        self.cog._edit_msg.assert_not_awaited()

    def test_split_cog_registers_all_music_commands(self):
        self.assertEqual(
            {command.name for command in MusicCog.__cog_app_commands__},
            {'음악', '재생', '일시정지', '다시재생', '정지', '스킵', '대기열', '구간이동', '반복', '대기열삭제', '대기열비우기', '대기열이동', '셔플'},
        )
