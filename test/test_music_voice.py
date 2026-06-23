import unittest
from pathlib import Path
from types import SimpleNamespace

from util.music.voice import (
    describe_voice_transition,
    ensure_music_voice_client,
    get_interaction_voice_channel,
    is_voice_client_active,
    same_voice_channel_error,
)


MISSING_CHANNEL_MESSAGE = "missing voice channel"
BUSY_CHANNEL_MESSAGE = "busy elsewhere"
MUSIC_VOICE_PATH = Path("util/music/voice.py")
LEGACY_MUSIC_VOICE_PATH = Path("util/music_voice.py")


class MusicVoiceTests(unittest.IsolatedAsyncioTestCase):
    def test_music_voice_helper_lives_under_music_package(self):
        self.assertTrue(MUSIC_VOICE_PATH.exists())
        self.assertFalse(LEGACY_MUSIC_VOICE_PATH.exists())

    async def test_missing_voice_client_and_missing_user_channel_returns_error(self):
        result = await ensure_music_voice_client(
            voice_client=None,
            user_channel=None,
            missing_channel_message=MISSING_CHANNEL_MESSAGE,
            busy_channel_message=BUSY_CHANNEL_MESSAGE,
        )

        self.assertIsNone(result.voice_client)
        self.assertEqual(result.error_message, MISSING_CHANNEL_MESSAGE)
        self.assertFalse(result.connected)
        self.assertFalse(result.moved)

    async def test_missing_voice_client_connects_to_user_channel(self):
        channel = _VoiceChannel("user")

        result = await ensure_music_voice_client(
            voice_client=None,
            user_channel=channel,
            missing_channel_message=MISSING_CHANNEL_MESSAGE,
            busy_channel_message=BUSY_CHANNEL_MESSAGE,
        )

        self.assertIs(result.voice_client, channel.connected_client)
        self.assertTrue(result.connected)
        self.assertFalse(result.moved)

    async def test_busy_voice_client_in_other_channel_returns_error_without_move(self):
        bot_channel = _VoiceChannel("bot")
        user_channel = _VoiceChannel("user")
        voice_client = _VoiceClient(bot_channel, playing=True)

        result = await ensure_music_voice_client(
            voice_client=voice_client,
            user_channel=user_channel,
            missing_channel_message=MISSING_CHANNEL_MESSAGE,
            busy_channel_message=BUSY_CHANNEL_MESSAGE,
        )

        self.assertIs(result.voice_client, voice_client)
        self.assertEqual(result.error_message, BUSY_CHANNEL_MESSAGE)
        self.assertFalse(result.connected)
        self.assertFalse(result.moved)
        self.assertIs(voice_client.channel, bot_channel)

    async def test_idle_voice_client_moves_to_user_channel(self):
        bot_channel = _VoiceChannel("bot")
        user_channel = _VoiceChannel("user")
        voice_client = _VoiceClient(bot_channel)

        result = await ensure_music_voice_client(
            voice_client=voice_client,
            user_channel=user_channel,
            missing_channel_message=MISSING_CHANNEL_MESSAGE,
            busy_channel_message=BUSY_CHANNEL_MESSAGE,
        )

        self.assertIs(result.voice_client, voice_client)
        self.assertIs(voice_client.channel, user_channel)
        self.assertFalse(result.connected)
        self.assertTrue(result.moved)

    async def test_same_channel_voice_client_is_returned_without_changes(self):
        channel = _VoiceChannel("shared")
        voice_client = _VoiceClient(channel, playing=True)

        result = await ensure_music_voice_client(
            voice_client=voice_client,
            user_channel=channel,
            missing_channel_message=MISSING_CHANNEL_MESSAGE,
            busy_channel_message=BUSY_CHANNEL_MESSAGE,
        )

        self.assertIs(result.voice_client, voice_client)
        self.assertIsNone(result.error_message)
        self.assertFalse(result.connected)
        self.assertFalse(result.moved)

    def test_is_voice_client_active_checks_playing_or_paused(self):
        self.assertFalse(is_voice_client_active(None))
        self.assertFalse(is_voice_client_active(_VoiceClient(_VoiceChannel("idle"))))
        self.assertTrue(
            is_voice_client_active(_VoiceClient(_VoiceChannel("playing"), playing=True))
        )
        self.assertTrue(
            is_voice_client_active(_VoiceClient(_VoiceChannel("paused"), paused=True))
        )

    def test_get_interaction_voice_channel_returns_user_voice_channel(self):
        channel = _VoiceChannel("user")
        interaction = SimpleNamespace(
            user=SimpleNamespace(voice=SimpleNamespace(channel=channel))
        )

        self.assertIs(get_interaction_voice_channel(interaction), channel)
        self.assertIsNone(get_interaction_voice_channel(SimpleNamespace(user=None)))

    def test_same_voice_channel_error_blocks_different_voice_channel(self):
        bot_channel = _VoiceChannel("bot")
        user_channel = _VoiceChannel("user")
        interaction = SimpleNamespace(
            user=SimpleNamespace(voice=SimpleNamespace(channel=user_channel))
        )
        voice_client = _VoiceClient(bot_channel)

        self.assertEqual(
            same_voice_channel_error(interaction, voice_client),
            "❌ 같은 음성 채널에 있는 사용자만 음악을 제어할 수 있습니다.",
        )

    def test_same_voice_channel_error_allows_same_or_missing_user_channel(self):
        channel = _VoiceChannel("shared")
        voice_client = _VoiceClient(channel)

        self.assertIsNone(
            same_voice_channel_error(
                SimpleNamespace(
                    user=SimpleNamespace(voice=SimpleNamespace(channel=channel))
                ),
                voice_client,
            )
        )
        self.assertEqual(
            same_voice_channel_error(SimpleNamespace(user=None), voice_client),
            "❌ 같은 음성 채널에 있는 사용자만 음악을 제어할 수 있습니다.",
        )

    def test_describe_voice_transition_returns_connected_or_moved_message(self):
        channel = _VoiceChannel("user")

        self.assertEqual(
            describe_voice_transition(
                SimpleNamespace(connected=True, moved=False),
                action="_play",
                user_channel=channel,
            ),
            "_play: connected to voice channel id={}".format(channel.id),
        )
        self.assertEqual(
            describe_voice_transition(
                SimpleNamespace(connected=False, moved=True),
                action="_play",
                user_channel=channel,
            ),
            "_play: moved to voice channel id={}".format(channel.id),
        )

    def test_describe_voice_transition_returns_none_without_transition_or_channel(self):
        self.assertIsNone(
            describe_voice_transition(
                SimpleNamespace(connected=False, moved=False),
                action="_play",
                user_channel=_VoiceChannel("user"),
            )
        )
        self.assertIsNone(
            describe_voice_transition(
                SimpleNamespace(connected=True, moved=False),
                action="_play",
                user_channel=None,
            )
        )


class _VoiceChannel:
    def __init__(self, name):
        self.name = name
        self.id = hash(name)
        self.connected_client = None

    async def connect(self):
        self.connected_client = _VoiceClient(self)
        return self.connected_client


class _VoiceClient:
    def __init__(self, channel, *, playing=False, paused=False):
        self.channel = channel
        self._playing = playing
        self._paused = paused

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return self._paused

    async def move_to(self, channel):
        self.channel = channel


if __name__ == "__main__":
    unittest.main()
