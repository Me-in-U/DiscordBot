import asyncio
import ast
import copy
import json
import threading
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from cogs.gambling.services import BalanceService
from util.message.recent import get_recent_messages, get_recent_message_images
from util.music.audio import BufferedOpusSource
from util.music.network import validate_music_url, run_extraction


def interaction(user_id=1):
    return SimpleNamespace(
        guild_id=1, guild=SimpleNamespace(id=1), channel_id=10,
        user=SimpleNamespace(id=user_id, mention=f"<@{user_id}>", display_avatar=None),
        created_at=datetime.now(timezone.utc),
        response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock(), is_done=lambda: False),
        followup=SimpleNamespace(send=AsyncMock()), original_response=AsyncMock(),
    )


class MemoryBalance(BalanceService):
    def __init__(self):
        self.money = {1: 100000}
        self.daily = None
        self.rounds = {}
        self.fail_date = False
        self.lock = asyncio.Lock()

    async def get_balance(self, guild, user):
        await asyncio.sleep(0)
        return self.money.get(int(user), 0)

    async def set_balance(self, guild, user, value):
        await asyncio.sleep(0)
        self.money[int(user)] = value

    async def can_use_daily(self, *args): return self.daily is None
    async def set_last_daily(self, guild, user, date):
        if self.fail_date: raise RuntimeError("date save failed")
        self.daily = date
    async def add_result(self, *args): pass
    async def get_stats(self, *args): return 0, 0, 0.0
    async def add_blackjack_result(self, *args): pass
    async def get_blackjack_stats(self, *args): return 0, 0, 0, 0.0
    async def reserve(self, key, guild, user, amount):
        await self.set_balance(guild,user,await self.get_balance(guild,user)-amount)
        self.rounds[key] = (int(user),self.rounds.get(key,(0,0))[1]+amount)
    async def settle(self, key, prize, *, recipient_id=None, amount=None):
        if key not in self.rounds: return False
        user, held = self.rounds[key]
        consumed = held if amount is None else amount
        await self.set_balance(1,recipient_id or user,await self.get_balance(1,recipient_id or user)+prize)
        if consumed == held: self.rounds.pop(key)
        else: self.rounds[key] = (user,held-consumed)
        return True

    @asynccontextmanager
    async def operation(self, guild):
        async with self.lock:
            saved = copy.deepcopy((self.money,self.daily,self.rounds))
            try: yield
            except BaseException:
                self.money,self.daily,self.rounds = saved
                raise


class FinancialRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.balance = MemoryBalance()
        self.patch = patch("cogs.gambling.operations.financial_transaction", self.balance.operation)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def test_concurrent_transfer_cannot_create_money(self):
        from cogs.gambling.transfer import execute_transfer
        self.balance.money = {1:100}
        targets = [SimpleNamespace(id=i,bot=False,mention=f"<@{i}>") for i in (2,3)]
        await asyncio.gather(*(execute_transfer(interaction(),self.balance,target_member=target,amount=60) for target in targets))
        self.assertEqual(sum(self.balance.money.values()),100)
        self.assertEqual(self.balance.money[1],40)

    async def test_recipient_write_failure_rolls_back_sender(self):
        from cogs.gambling.transfer import execute_transfer
        original = self.balance.set_balance
        async def fail(guild,user,amount):
            if int(user)==2: raise RuntimeError("recipient write failed")
            await original(guild,user,amount)
        self.balance.set_balance = fail
        with self.assertRaises(RuntimeError):
            await execute_transfer(interaction(),self.balance,target_member=SimpleNamespace(id=2,bot=False,mention="receiver"),amount=60)
        self.assertEqual(self.balance.money,{1:100000})

    async def test_daily_date_failure_does_not_credit_money(self):
        from cogs.gambling.daily_reward import grant_daily_money
        self.balance.fail_date=True
        with self.assertRaises(RuntimeError): await grant_daily_money(interaction(),self.balance)
        self.assertEqual(self.balance.money[1],100000)
        self.balance.fail_date=False
        await grant_daily_money(interaction(),self.balance)
        await grant_daily_money(interaction(),self.balance)
        self.assertEqual(self.balance.money[1],110000)

    async def test_all_previously_broken_game_entries_await_service(self):
        from cogs.gambling.instant_lottery import run_instant_lottery
        from cogs.gambling.ladder import run_ladder_game
        from cogs.gambling.slot_machine import run_slot_machine
        from cogs.gambling.rps import run_rock_paper_scissors
        from cogs.gambling.sprinkle_command import run_sprinkle
        calls=[(run_instant_lottery,{}),(run_ladder_game,{"bet_amount":100}),
               (run_slot_machine,{"bet_amount":100}),(run_rock_paper_scissors,{"choice_value":"가위","bet_amount":100}),
               (run_sprinkle,{"total_amount":100,"people":2})]
        for func,kwargs in calls:
            with self.subTest(game=func.__name__):
                request=interaction()
                await func(request,self.balance,**kwargs)
                request.response.send_message.assert_awaited()

    async def test_slot_spin_uses_async_balance(self):
        from cogs.gambling.slot_machine import SlotMachineView
        view=SlotMachineView(balance=self.balance,guild_id="1",user_id="1",bet_amount=100)
        embed, insufficient=await view._spin(interaction())
        self.assertIsInstance(embed,discord.Embed)
        self.assertFalse(insufficient)

    async def test_blackjack_timeout_returns_reserved_stake(self):
        from cogs.gambling.blackjack import BlackjackView
        view=BlackjackView(balance=self.balance,guild_id="1",user_id="1",bet_amount=100)
        await view.start()
        self.assertEqual(self.balance.money[1],99900)
        await view.on_timeout()
        await view.on_timeout()
        self.assertEqual(self.balance.money[1],100000)

    async def test_double_callbacks_do_not_reserve_twice(self):
        from cogs.gambling.blackjack import BlackjackView
        view=BlackjackView(balance=self.balance,guild_id="1",user_id="1",bet_amount=100)
        await view.start()
        with patch.object(view,"_dealer_play",AsyncMock()), patch.object(view,"_build_embed",AsyncMock(return_value=discord.Embed())):
            await asyncio.gather(view.double_button.callback(interaction()),view.double_button.callback(interaction()))
        self.assertEqual(view.current_bet,200)

    async def test_sprinkle_timeout_refunds_only_unclaimed_amount(self):
        from cogs.gambling.sprinkle import SprinkleView
        view=SprinkleView(balance=self.balance,parts_list=[40,60],sender_user=interaction().user,guild_id="1")
        await self.balance.reserve(view.round_id,1,1,100)
        await view.claim_button.callback(interaction(2))
        await view.on_timeout()
        self.assertEqual(self.balance.money,{1:99940,2:60})


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_private_channel_and_legacy_entries_are_excluded(self):
        client=SimpleNamespace(USER_MESSAGES={1:{"user":[
            {"channel_id":10,"content":"public"}, {"channel_id":20,"content":"PRIVATE"}, {"content":"LEGACY"}]}})
        value=get_recent_messages(client,1,channel_id=10)
        self.assertIn("public",value)
        self.assertNotIn("PRIVATE",value)
        self.assertNotIn("LEGACY",value)

    def test_no_history_permission_returns_no_ai_context(self):
        client=SimpleNamespace(USER_MESSAGES={1:{"user":[{"channel_id":10,"content":"secret"}]}},get_channel=lambda _:SimpleNamespace(permissions_for=lambda _:SimpleNamespace(read_message_history=False)))
        self.assertEqual(get_recent_messages(client,1,channel_id=10,requester=object()),"")

    def test_private_images_are_excluded(self):
        client=SimpleNamespace(USER_MESSAGES={1:{"user":[{"channel_id":20,"content":[{"type":"input_image","image_url":"private"}]}]}})
        self.assertEqual(get_recent_message_images(client,1,channel_id=10),())

    def test_internal_and_deceptive_urls_are_rejected(self):
        for url in ["http://127.0.0.1/","http://host.docker.internal/","https://youtube.com.evil.test/","https://youtube.com@evil.test/","https://youtube.com:8443/watch?v=1","file:///etc/passwd"]:
            with self.subTest(url=url),self.assertRaises(ValueError): validate_music_url(url)
        self.assertEqual(validate_music_url("http://youtu.be/123"),"https://youtu.be/123")

    async def test_rejected_music_url_never_reaches_extractor(self):
        from util.music.source import YTDLSource
        with patch("util.music.source._extract_info_with_fallback") as extract:
            with self.assertRaises(ValueError): await YTDLSource.from_url("http://127.0.0.1/private")
        extract.assert_not_called()

    def test_buffer_keeps_ffmpeg_exit_error_visible(self):
        source=SimpleNamespace(read=Mock(side_effect=[b"opus"]*10+[b""]),_current_error=RuntimeError("ffmpeg exit"))
        buffered=BufferedOpusSource(source);buffered.prime()
        for _ in range(10): buffered.read()
        self.assertEqual(buffered.read(),b"")
        self.assertIs(buffered._current_error,source._current_error)

    async def test_health_not_ready_returns_503(self):
        from cogs.status_api import StatusApi
        owner=SimpleNamespace(bot=SimpleNamespace(is_ready=lambda:False,guilds=[],latency=0,user=None),start_time=0)
        response=await StatusApi.health_handler(owner,None)
        self.assertEqual(response.status,503)

    async def test_health_db_failure_returns_503(self):
        from cogs.status_api import StatusApi
        owner=SimpleNamespace(bot=SimpleNamespace(is_ready=lambda:True,guilds=[],latency=0,user=None),start_time=0)
        with patch("cogs.status_api.ensure_schema_ready",AsyncMock(side_effect=RuntimeError("DB offline"))),self.assertLogs("cogs.status_api",level="ERROR"):
            self.assertEqual((await StatusApi.health_handler(owner,None)).status,503)

    async def test_failed_weekly_read_never_clears_records(self):
        from util.loop.weekly_1557_reporter import run_weekly_1557_report
        clear=AsyncMock();send=AsyncMock()
        with self.assertLogs("util.loop.weekly_1557_reporter",level="ERROR"):
            result=await run_weekly_1557_report(SimpleNamespace(get_channel=lambda _:SimpleNamespace(send=send)),target_channel_id=1,now=datetime(2026,10,12),fetch_counts=AsyncMock(side_effect=RuntimeError("DB read failed")),clear_counts=clear,log=lambda _:None)
        self.assertFalse(result);clear.assert_not_awaited();send.assert_not_awaited()

    async def test_daily_refresh_failure_does_not_skip_other_jobs(self):
        from util.loop.daily_refresh_runner import run_daily_refreshes
        next_job=AsyncMock(return_value=[]);reload=AsyncMock();bot=SimpleNamespace(USER_MESSAGES={1:{}})
        with self.assertLogs("util.loop.daily_refresh_runner",level="ERROR"):
            await run_daily_refreshes(bot,now=datetime(2026,10,12),reload_recent_messages=reload,refresh_celebration=AsyncMock(side_effect=RuntimeError("DB failed")),refresh_dday=next_job,log=lambda _:None)
        next_job.assert_awaited_once();reload.assert_awaited_once()

    async def test_party_deletion_requires_permissions(self):
        from cogs.party import Party
        request=interaction();request.user.guild_permissions=SimpleNamespace(manage_channels=False)
        request.channel=SimpleNamespace(name="a-채팅o",category=SimpleNamespace(delete=AsyncMock()))
        owner=SimpleNamespace(bot=SimpleNamespace(PARTY_LIST={}))
        await Party.release_party.callback(owner,request)
        request.channel.category.delete.assert_not_awaited()

    async def test_voice_stop_cannot_disconnect_music(self):
        from cogs.voice_chat import VoiceChat
        voice=SimpleNamespace(channel=SimpleNamespace(id=5),disconnect=AsyncMock())
        request=interaction();request.guild.voice_client=voice;request.user.voice=None
        owner=VoiceChat(SimpleNamespace())
        await VoiceChat.stop_chat.callback(owner,request)
        voice.disconnect.assert_not_awaited()

    def test_long_ai_text_is_attached_and_mentions_disabled(self):
        from common.discord_output import text_options
        options=text_options("x"*2100)
        self.assertIn("file",options)
        self.assertLessEqual(len(options["content"]),2000)
        options["file"].close()
        self.assertFalse(text_options("@everyone")["allowed_mentions"].everyone)

    def test_deploy_secrets_are_excluded(self):
        rules=Path(".dockerignore").read_text().splitlines()
        self.assertIn(".env.*",rules);self.assertIn("cookies.txt",rules)

    def test_no_unawaited_balance_calls_remain(self):
        for path in Path("cogs/gambling").glob("*.py"):
            tree=ast.parse(path.read_text(encoding="utf-8"))
            parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {"get_balance","set_balance","get_stats","set_last_daily"}:
                    self.assertIsInstance(parents[node],ast.Await,f"{path}:{node.lineno}")

    async def test_discord_nonce_enforcement_handles_files(self):
        from util.notification_delivery import _send_enforced
        async def send(channel_id, *,params):
            if params.payload is not None: payload=params.payload
            else: payload=json.loads(next(p['value'] for p in params.multipart if p['name']=='payload_json'))
            self.assertTrue(payload['enforce_nonce']);self.assertEqual(payload['nonce'],'stable')
            return {'id':'1'}
        state=SimpleNamespace(http=SimpleNamespace(send_message=send),create_message=lambda **kwargs:kwargs['data'])
        target=SimpleNamespace(id=1,_state=state)
        import io
        await _send_enforced(target,'stable','hello',{})
        await _send_enforced(target,'stable','hello',{'file':discord.File(io.BytesIO(b'file'),filename='test.txt')})
