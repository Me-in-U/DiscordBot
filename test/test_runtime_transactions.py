import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord
from util import db
from util import notification_delivery as delivery


class TransactionTests(unittest.IsolatedAsyncioTestCase):
    def connection(self):
        return SimpleNamespace(begin=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock(), close=MagicMock())

    async def test_nested_queries_commit_once_and_share_connection(self):
        conn = self.connection()
        @asynccontextmanager
        async def acquire():
            yield conn
        pool = SimpleNamespace(acquire=acquire)
        with patch.object(db, "get_db_pool", AsyncMock(return_value=pool)):
            async with db.transaction() as outer:
                async with db.transaction() as inner:
                    self.assertIs(outer, inner)
                async with db.db_connection() as query_conn:
                    self.assertIs(query_conn, conn)
        conn.begin.assert_awaited_once(); conn.commit.assert_awaited_once()
        conn.rollback.assert_not_awaited()

    async def test_failure_and_cancellation_roll_back(self):
        for error in (RuntimeError("write failed"), asyncio.CancelledError()):
            conn = self.connection()
            @asynccontextmanager
            async def acquire():
                yield conn
            with patch.object(db,"get_db_pool",AsyncMock(return_value=SimpleNamespace(acquire=acquire))):
                with self.assertRaises(type(error)):
                    async with db.transaction():
                        raise error
            conn.rollback.assert_awaited_once(); conn.commit.assert_not_awaited()

    async def test_child_task_does_not_inherit_parent_connection(self):
        connections = [self.connection(), self.connection()]
        @asynccontextmanager
        async def acquire():
            yield connections.pop(0)
        with patch.object(db,"get_db_pool",AsyncMock(return_value=SimpleNamespace(acquire=acquire))):
            async with db.transaction() as parent:
                async def child():
                    async with db.db_connection() as conn:
                        self.assertIsNot(conn, parent)
                await asyncio.create_task(child())

    async def test_database_deadline_rolls_back(self):
        conn = self.connection()
        @asynccontextmanager
        async def acquire():
            yield conn
        with patch.object(db,"get_db_pool",AsyncMock(return_value=SimpleNamespace(acquire=acquire))), patch.object(db,"DB_OPERATION_TIMEOUT",0.01):
            with self.assertRaises(TimeoutError):
                async with db.transaction():
                    await asyncio.sleep(1)
        conn.rollback.assert_awaited_once()


class NotificationDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.target=MagicMock(spec=discord.TextChannel)
        self.target.id=10
        self.target._state=SimpleNamespace(user=SimpleNamespace(id=1))
        self.row=dict(message_id=None,lease_until=None,attempted_at=None,created_at=datetime.utcnow(),payload=json.dumps({"content":"notice","embeds":[]}))
        self.write=AsyncMock();self.send=AsyncMock(return_value=SimpleNamespace(id=99))
        @asynccontextmanager
        async def transaction(): yield
        self.patches=[patch.object(delivery,"transaction",transaction),patch.object(delivery,"fetch_one",AsyncMock(side_effect=lambda *args:self.row)),patch.object(delivery,"execute_query",self.write),patch.object(delivery,"_send_enforced",self.send)]
        for patcher in self.patches: patcher.start();self.addCleanup(patcher.stop)
        self.messages=[]
        async def history(**kwargs):
            for message in self.messages: yield message
        self.target.history=history

    async def test_first_delivery_has_stable_nonce_and_records_message(self):
        result=await delivery.send_once(self.target,"event1","notice")
        self.assertEqual(result.id,99)
        self.assertEqual(len(self.send.await_args.args[1]),24)
        self.assertFalse(self.send.await_args.args[3]["allowed_mentions"].everyone)
        self.assertIn("message_id",self.write.await_args.args[0])

    async def test_unrelated_notifications_do_not_block_each_other(self):
        started=0
        both=asyncio.Event()
        async def send(*args):
            nonlocal started
            started+=1
            if started==2: both.set()
            await both.wait()
            return SimpleNamespace(id=99)
        self.send.side_effect=send
        await asyncio.wait_for(asyncio.gather(delivery.send_once(self.target,"first","notice"),delivery.send_once(self.target,"second","notice")),timeout=1)
        self.assertEqual(started,2)

    async def test_completed_and_leased_delivery_are_never_sent_again(self):
        self.row["message_id"]=99
        self.assertEqual((await delivery.send_once(self.target,"event1","notice")).id,99)
        self.row["message_id"]=None;self.row["lease_until"]=datetime.utcnow()+timedelta(seconds=30)
        with self.assertRaises(RuntimeError): await delivery.send_once(self.target,"event1","notice")
        self.send.assert_not_awaited()

    async def test_sent_message_is_recovered_after_state_save_failure(self):
        self.row["attempted_at"]=datetime.utcnow()-timedelta(minutes=4)
        message=SimpleNamespace(id=99,author=SimpleNamespace(id=1),content="notice",embeds=[])
        self.messages=[message]
        self.assertIs(await delivery.send_once(self.target,"event1","notice"),message)
        self.send.assert_not_awaited()

    async def test_ambiguous_old_delivery_stops_instead_of_duplicate(self):
        self.row["attempted_at"]=datetime.utcnow()-timedelta(minutes=4)
        with self.assertRaisesRegex(RuntimeError,"관리자"):
            await delivery.send_once(self.target,"event1","notice")
        self.send.assert_not_awaited()

    async def test_recent_retry_reuses_same_nonce(self):
        self.row["attempted_at"]=datetime.utcnow()-timedelta(seconds=70)
        await delivery.send_once(self.target,"event1","notice")
        first=self.send.await_args.args[1]
        await delivery.send_once(self.target,"event1","notice")
        self.assertEqual(self.send.await_args.args[1],first)

class FinancialViewRollbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_view_stop_waits_for_successful_database_commit(self):
        from cogs.gambling.operations import financial_operation
        from cogs.gambling.services import BalanceService
        owner=SimpleNamespace(balance=BalanceService(),guild_id=1,finished=False,stop=Mock())
        original_stop=owner.stop
        @asynccontextmanager
        async def failed_commit(guild):
            yield
            raise RuntimeError("commit failed")
        @financial_operation
        async def finish(view):
            view.finished=True;view.stop()
        with patch("cogs.gambling.operations.financial_transaction",failed_commit):
            with self.assertRaises(RuntimeError): await finish(owner)
        self.assertFalse(owner.finished);original_stop.assert_not_called()

class MigrationEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_converts_nontransactional_balance_table(self):
        cursor=MagicMock();cursor.__aenter__=AsyncMock(return_value=cursor)
        cursor.execute=AsyncMock()
        async def fetch():
            table=cursor.execute.await_args.args[1][1]
            return ("MyISAM" if table=="gambling_balances" else "InnoDB",)
        cursor.fetchone=fetch
        conn=SimpleNamespace(cursor=Mock(return_value=cursor))
        acquire=MagicMock();acquire.__aenter__=AsyncMock(return_value=conn)
        pool=SimpleNamespace(acquire=Mock(return_value=acquire))
        with patch.object(db,"get_db_pool",AsyncMock(return_value=pool)),patch.object(db,"_ensure_bigint_unsigned",AsyncMock()),patch.object(db,"_ensure_column",AsyncMock()):
            await db.run_schema_migrations()
        alters=[call.args[0] for call in cursor.execute.await_args_list if "ENGINE=InnoDB" in call.args[0]]
        self.assertEqual(alters,["ALTER TABLE gambling_balances ENGINE=InnoDB"])
