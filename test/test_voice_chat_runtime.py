import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import cogs.voice_chat as voice_chat_module
from cogs.voice_chat import VoiceChat
from cogs.voice_chat.settings import (
    CPU_WHISPER_COMPUTE_TYPE,
    CPU_WHISPER_MODEL,
    CUDA_WHISPER_COMPUTE_TYPE,
    CUDA_WHISPER_MODEL,
    resolve_whisper_settings,
)


class FakeVoiceRecvClient:
    def __init__(self, channel) -> None:
        self.channel = channel
        self._listening = False
        self.disconnect = AsyncMock()
        self.move_to = AsyncMock()

    def is_listening(self) -> bool:
        return self._listening

    def stop_listening(self) -> None:
        self._listening = False


def build_interaction(*, guild, channel, user_voice=True):
    response = SimpleNamespace(
        defer=AsyncMock(),
        send_message=AsyncMock(),
    )
    followup = SimpleNamespace(send=AsyncMock())
    voice_state = SimpleNamespace(channel=channel) if user_voice else None
    user = SimpleNamespace(
        id=100,
        name="tester",
        voice=voice_state,
    )
    return SimpleNamespace(
        guild=guild,
        channel=SimpleNamespace(send=AsyncMock(return_value=AsyncMock())),
        user=user,
        response=response,
        followup=followup,
    )


class VoiceChatSettingsTests(unittest.TestCase):
    def test_default_settings_use_lightweight_cpu_model(self):
        settings = resolve_whisper_settings({})

        self.assertEqual(CPU_WHISPER_MODEL, settings.model)
        self.assertEqual("cpu", settings.device)
        self.assertEqual(CPU_WHISPER_COMPUTE_TYPE, settings.compute_type)

    def test_cuda_settings_require_explicit_device_selection(self):
        settings = resolve_whisper_settings(
            {"VOICE_CHAT_WHISPER_DEVICE": "cuda"}
        )

        self.assertEqual(CUDA_WHISPER_MODEL, settings.model)
        self.assertEqual("cuda", settings.device)
        self.assertEqual(CUDA_WHISPER_COMPUTE_TYPE, settings.compute_type)

    def test_invalid_device_falls_back_to_cpu_defaults(self):
        settings = resolve_whisper_settings(
            {"VOICE_CHAT_WHISPER_DEVICE": "automatic"}
        )

        self.assertEqual(CPU_WHISPER_MODEL, settings.model)
        self.assertEqual("cpu", settings.device)
        self.assertEqual(CPU_WHISPER_COMPUTE_TYPE, settings.compute_type)


class VoiceChatRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bot = SimpleNamespace(loop=asyncio.get_running_loop())
        self.cog = VoiceChat(bot)

    async def asyncTearDown(self):
        for guild_id in list(self.cog.active_chats):
            self.cog._cancel_guild_tasks(guild_id)
        await asyncio.sleep(0)

    async def test_model_loader_uses_cpu_tiny_once_by_default(self):
        model = object()
        environment = {
            "VOICE_CHAT_WHISPER_DEVICE": "cpu",
            "VOICE_CHAT_WHISPER_MODEL": "",
            "VOICE_CHAT_WHISPER_COMPUTE_TYPE": "",
        }

        with (
            patch.dict(os.environ, environment),
            patch("shutil.which", return_value="ffmpeg"),
            patch.object(
                voice_chat_module,
                "WhisperModel",
                return_value=model,
            ) as whisper_model,
        ):
            await asyncio.gather(
                self.cog.load_model(),
                self.cog.load_model(),
            )

        self.assertIs(model, self.cog.model)
        whisper_model.assert_called_once_with(
            CPU_WHISPER_MODEL,
            device="cpu",
            compute_type=CPU_WHISPER_COMPUTE_TYPE,
        )

    async def test_start_chat_acknowledges_interaction_and_keys_task_by_guild(self):
        voice_channel = SimpleNamespace(id=200)
        voice_client = FakeVoiceRecvClient(voice_channel)
        voice_channel.connect = AsyncMock(return_value=voice_client)
        guild = SimpleNamespace(id=300, voice_client=None)
        interaction = build_interaction(
            guild=guild,
            channel=voice_channel,
        )
        self.cog.chat_loop = AsyncMock()
        self.cog.display_loop = AsyncMock()
        fake_voice_recv = SimpleNamespace(VoiceRecvClient=FakeVoiceRecvClient)

        with patch.object(voice_chat_module, "voice_recv", fake_voice_recv):
            await VoiceChat.start_chat.callback(self.cog, interaction)

        interaction.response.defer.assert_awaited_once_with(
            ephemeral=True,
            thinking=True,
        )
        interaction.followup.send.assert_awaited_once()
        self.assertIn(guild.id, self.cog.active_chats)
        self.assertNotIn(interaction.user.id, self.cog.active_chats)

    async def test_start_chat_reports_voice_connection_failure(self):
        voice_channel = SimpleNamespace(id=200)
        voice_channel.connect = AsyncMock(
            side_effect=RuntimeError("voice connection failed")
        )
        guild = SimpleNamespace(id=300, voice_client=None)
        interaction = build_interaction(
            guild=guild,
            channel=voice_channel,
        )
        fake_voice_recv = SimpleNamespace(VoiceRecvClient=FakeVoiceRecvClient)

        with patch.object(voice_chat_module, "voice_recv", fake_voice_recv):
            await VoiceChat.start_chat.callback(self.cog, interaction)

        interaction.response.defer.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()
        self.assertNotIn(guild.id, self.cog.active_chats)
        self.assertNotIn(guild.id, self.cog.chat_data)

    async def test_start_chat_without_voice_channel_responds_immediately(self):
        guild = SimpleNamespace(id=300, voice_client=None)
        interaction = build_interaction(
            guild=guild,
            channel=None,
            user_voice=False,
        )
        fake_voice_recv = SimpleNamespace(VoiceRecvClient=FakeVoiceRecvClient)

        with patch.object(voice_chat_module, "voice_recv", fake_voice_recv):
            await VoiceChat.start_chat.callback(self.cog, interaction)

        interaction.response.send_message.assert_awaited_once_with(
            "음성 채널에 먼저 입장해주세요.",
            ephemeral=True,
        )
        interaction.response.defer.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
