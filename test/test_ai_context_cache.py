import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

os.environ.setdefault("OPENAI_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("SONPANNO_GUILD_ID", "123")
os.environ.setdefault("SSAFY_GUILD_ID", "456")

import bot
from util.message.recent import get_interaction_context, get_recent_messages


class ContextCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cache_patch = patch.object(bot.DISCORD_CLIENT, "USER_MESSAGES", {})
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.author = SimpleNamespace(id=99, name="Bot", display_name="봇", bot=True)

    def message(self, content="답변", message_id=42, embeds=()):
        return SimpleNamespace(
            id=message_id, author=self.author, content=content, embeds=embeds,
            attachments=[], guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=10),
            created_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
        )

    async def test_bot_reply_and_embed_are_cached_without_running_commands(self):
        message = self.message(embeds=[discord.Embed(title="제목", description="본문")])
        with patch.object(bot.DISCORD_CLIENT, "_connection") as connection, patch.object(
            bot.DISCORD_CLIENT, "process_commands", AsyncMock()
        ) as commands:
            connection.user = self.author
            await bot.on_message(message)
        result = get_recent_messages(bot.DISCORD_CLIENT, 1, channel_id=10)
        self.assertIn("봇(assistant): 답변", result)
        self.assertIn("제목", result)
        self.assertIn("본문", result)
        commands.assert_not_awaited()

    async def test_edit_replaces_reply_once_and_delete_removes_it(self):
        bot.cache_discord_message(self.message("처리 중"))
        payload = SimpleNamespace(guild_id=1, channel_id=10, message_id=42)
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=self.message("완료된 답변")))
        with patch.object(bot.DISCORD_CLIENT, "get_channel", return_value=channel):
            await bot.on_raw_message_edit(payload)
        messages = bot.DISCORD_CLIENT.USER_MESSAGES[1]["99"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"][0]["text"], "완료된 답변")
        await bot.on_raw_message_delete(payload)
        self.assertEqual(bot.DISCORD_CLIENT.USER_MESSAGES[1]["99"], [])

    async def test_failed_edit_fetch_does_not_keep_stale_content(self):
        bot.cache_discord_message(self.message("수정 전"))
        error = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "denied")
        channel = SimpleNamespace(fetch_message=AsyncMock(side_effect=error))
        with patch.object(bot.DISCORD_CLIENT, "get_channel", return_value=channel):
            await bot.on_raw_message_edit(SimpleNamespace(guild_id=1, channel_id=10, message_id=42))
        self.assertEqual(bot.DISCORD_CLIENT.USER_MESSAGES[1]["99"], [])

    async def test_deferred_blank_reply_is_cached_when_final_answer_arrives(self):
        bot.cache_discord_message(self.message(""))
        self.assertEqual(bot.DISCORD_CLIENT.USER_MESSAGES, {})
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=self.message("최종 답변")))
        with patch.object(bot.DISCORD_CLIENT, "get_channel", return_value=channel):
            await bot.on_raw_message_edit(SimpleNamespace(guild_id=1, channel_id=10, message_id=42))
        self.assertIn("최종 답변", get_recent_messages(bot.DISCORD_CLIENT, 1, channel_id=10))

    def test_context_keeps_latest_twenty_in_order_with_bot_and_human_roles(self):
        for index in range(1, 26):
            message = self.message(f"발화 {index}", message_id=index)
            if index % 2:
                message.author = SimpleNamespace(id=1, name="User", bot=False)
            bot.cache_discord_message(message)
        edited = self.message("발화 25 수정", message_id=25)
        edited.author = SimpleNamespace(id=1, name="User", bot=False)
        bot.cache_discord_message(edited)
        interaction = SimpleNamespace(guild_id=1, channel_id=10, user=object())
        channel = SimpleNamespace(permissions_for=lambda _: SimpleNamespace(
            read_message_history=True, view_channel=True,
        ))
        with patch.object(bot.DISCORD_CLIENT, "get_channel", return_value=channel):
            result = get_interaction_context(bot.DISCORD_CLIENT, interaction)
        self.assertEqual(len(result.splitlines()), 20)
        self.assertIn("발화 6", result.splitlines()[0])
        self.assertIn("발화 25 수정", result.splitlines()[-1])
        self.assertIn("(assistant)", result)
        self.assertIn("(user)", result)

    def test_reload_deduplicates_message_ids(self):
        bot.cache_discord_message(self.message())
        bot.cache_discord_message(self.message())
        self.assertEqual(len(bot.DISCORD_CLIENT.USER_MESSAGES[1]["99"]), 1)


class CommandContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_ai_commands_receive_current_channel_bot_context(self):
        from cogs.explanation import ExplanationCommands
        from cogs.interpret import InterpretCommands
        from cogs.meal_recommendation import MealRecommendationCommands
        from cogs.search import SearchCommands
        from cogs.translation import TranslationCommands

        channel = SimpleNamespace(permissions_for=lambda _: SimpleNamespace(
            read_message_history=True, view_channel=True,
        ))
        client = SimpleNamespace(
            USER_MESSAGES={1: {"bot": [{
                "role": "assistant", "content": "앞선 봇 답변", "channel_id": 10,
            }, {"role": "assistant", "content": "다른 채널 비밀", "channel_id": 20}]}},
            get_channel=lambda _: channel,
        )
        for cog_type, module, method, variable in (
            (ExplanationCommands, "explanation", "explain", "previous_messages"),
            (InterpretCommands, "interpret", "interpret", "previous_messages"),
            (TranslationCommands, "translation", "translate", "recent_messages"),
            (SearchCommands, "search", "search", "recent_messages"),
            (MealRecommendationCommands, "meal_recommendation", "recommend_meal", "recent_messages"),
        ):
            with self.subTest(command=method):
                interaction = SimpleNamespace(
                    guild_id=1, channel_id=10, user=SimpleNamespace(id=1),
                    response=SimpleNamespace(defer=AsyncMock()),
                    followup=SimpleNamespace(send=AsyncMock()),
                )
                cog = cog_type(client)
                args = ("그거 다시 설명해줘",)
                if method == "recommend_meal":
                    cog._remaining_cuisines["guild:1"] = ["한식"]
                    args = ()
                with patch(f"cogs.{module}.custom_prompt_model", return_value="비빔밥") as model:
                    await getattr(cog, method).callback(cog, interaction, *args)
                value = model.call_args.kwargs["prompt"]["variables"][variable]
                self.assertIn("bot(assistant): 앞선 봇 답변", value)
                self.assertNotIn("다른 채널 비밀", value)


if __name__ == "__main__":
    unittest.main()
