import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import cogs.voice_chat as voice_chat_module
from cogs.voice_chat import StreamingSink, VoiceChat
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


class StreamingSinkTests(unittest.TestCase):
    def build_sink(self, *, dave_protocol_version=1):
        session = Mock()
        connection = SimpleNamespace(
            dave_session=session,
            dave_protocol_version=dave_protocol_version,
        )
        vc = SimpleNamespace(
            guild=SimpleNamespace(id=300),
            _connection=connection,
        )
        cog = SimpleNamespace(bot=SimpleNamespace(loop=Mock()))
        command_user = SimpleNamespace(id=100)
        return StreamingSink(cog, command_user, vc), session

    def test_sink_accepts_opus_to_decrypt_dave_before_decoding(self):
        sink, session = self.build_sink()
        user = SimpleNamespace(id=101)
        data = SimpleNamespace(
            packet=SimpleNamespace(ssrc=55),
            opus=b"encrypted-opus",
        )
        decoder = Mock()
        decoder.decode.return_value = b"decoded-pcm"
        session.decrypt.return_value = b"plain-opus"

        with patch.object(
            voice_chat_module.discord.opus,
            "Decoder",
            return_value=decoder,
        ):
            pcm = sink._decode_voice_packet(user, data)

        self.assertTrue(sink.wants_opus())
        session.decrypt.assert_called_once_with(
            user.id,
            voice_chat_module.davey.MediaType.audio,
            b"encrypted-opus",
        )
        decoder.decode.assert_called_once_with(b"plain-opus", fec=False)
        self.assertEqual(b"decoded-pcm", pcm)

    def test_sink_skips_dave_decryption_when_protocol_is_disabled(self):
        sink, session = self.build_sink(dave_protocol_version=0)
        user = SimpleNamespace(id=101)
        data = SimpleNamespace(
            packet=SimpleNamespace(ssrc=55),
            opus=b"plain-opus",
        )
        decoder = Mock()
        decoder.decode.return_value = b"decoded-pcm"

        with patch.object(
            voice_chat_module.discord.opus,
            "Decoder",
            return_value=decoder,
        ):
            pcm = sink._decode_voice_packet(user, data)

        session.decrypt.assert_not_called()
        decoder.decode.assert_called_once_with(b"plain-opus", fec=False)
        self.assertEqual(b"decoded-pcm", pcm)

    def test_sink_does_not_decrypt_fabricated_loss_packet(self):
        class FakeLossPacket:
            ssrc = 55

            def __bool__(self):
                return False

        sink, session = self.build_sink()
        user = SimpleNamespace(id=101)
        data = SimpleNamespace(packet=FakeLossPacket(), opus=b"opus-silence")
        decoder = Mock()
        decoder.decode.return_value = b"decoded-pcm"

        with patch.object(
            voice_chat_module.discord.opus,
            "Decoder",
            return_value=decoder,
        ):
            pcm = sink._decode_voice_packet(user, data)

        session.decrypt.assert_not_called()
        decoder.decode.assert_called_once_with(b"opus-silence", fec=False)
        self.assertEqual(b"decoded-pcm", pcm)

    def test_corrupt_opus_packet_is_dropped_without_raising(self):
        class FakeOpusError(Exception):
            pass

        sink, session = self.build_sink()
        user = SimpleNamespace(id=101)
        data = SimpleNamespace(
            packet=SimpleNamespace(ssrc=55),
            opus=b"encrypted-opus",
        )
        decoder = Mock()
        decoder.decode.side_effect = FakeOpusError("corrupt stream")
        session.decrypt.return_value = b"corrupt-opus"

        with (
            patch.object(
                voice_chat_module.discord.opus,
                "Decoder",
                return_value=decoder,
            ),
            patch.object(
                voice_chat_module.discord.opus,
                "OpusError",
                FakeOpusError,
            ),
        ):
            pcm = sink._decode_voice_packet(user, data)

        self.assertIsNone(pcm)
        self.assertNotIn(55, sink.opus_decoders)
        self.assertEqual(1, sink.decode_error_counts["opus"])


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

    async def test_chat_loop_disconnects_when_receiver_stops_unexpectedly(self):
        receive_error = RuntimeError("receiver failed")
        vc = SimpleNamespace(
            is_connected=Mock(return_value=True),
            is_listening=Mock(return_value=False),
            listen=Mock(),
            disconnect=AsyncMock(),
        )

        def invoke_after(_sink, *, after):
            after(receive_error)

        vc.listen.side_effect = invoke_after
        self.cog.load_model = AsyncMock()
        command_user = SimpleNamespace(name="tester")

        await self.cog.chat_loop(command_user, vc, guild_id=300)

        vc.listen.assert_called_once()
        vc.disconnect.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
