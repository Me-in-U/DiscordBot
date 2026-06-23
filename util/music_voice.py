from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MusicVoiceClientResult:
    voice_client: Any | None
    error_message: str | None = None
    connected: bool = False
    moved: bool = False


SAME_VOICE_CHANNEL_MESSAGE = "❌ 같은 음성 채널에 있는 사용자만 음악을 제어할 수 있습니다."


def get_interaction_voice_channel(interaction: Any) -> Any | None:
    member = getattr(interaction, "user", None)
    voice = getattr(member, "voice", None)
    return getattr(voice, "channel", None)


def same_voice_channel_error(
    interaction: Any,
    voice_client: Any,
    *,
    message: str = SAME_VOICE_CHANNEL_MESSAGE,
) -> str | None:
    user_channel = get_interaction_voice_channel(interaction)
    bot_channel = getattr(voice_client, "channel", None)
    if bot_channel is None:
        return None
    if user_channel != bot_channel:
        return message
    return None


def describe_voice_transition(
    result: Any,
    *,
    action: str,
    user_channel: Any | None,
) -> str | None:
    if user_channel is None:
        return None
    if getattr(result, "connected", False):
        return f"{action}: connected to voice channel id={user_channel.id}"
    if getattr(result, "moved", False):
        return f"{action}: moved to voice channel id={user_channel.id}"
    return None


def is_voice_client_active(voice_client: Any | None) -> bool:
    return bool(
        voice_client and (voice_client.is_playing() or voice_client.is_paused())
    )


async def ensure_music_voice_client(
    *,
    voice_client: Any | None,
    user_channel: Any | None,
    missing_channel_message: str,
    busy_channel_message: str,
) -> MusicVoiceClientResult:
    if voice_client is None:
        if user_channel is None:
            return MusicVoiceClientResult(
                voice_client=None,
                error_message=missing_channel_message,
            )
        return MusicVoiceClientResult(
            voice_client=await user_channel.connect(),
            connected=True,
        )

    if user_channel is None:
        return MusicVoiceClientResult(
            voice_client=voice_client,
            error_message=missing_channel_message,
        )

    if getattr(voice_client, "channel", None) != user_channel:
        if is_voice_client_active(voice_client):
            return MusicVoiceClientResult(
                voice_client=voice_client,
                error_message=busy_channel_message,
            )
        await voice_client.move_to(user_channel)
        return MusicVoiceClientResult(
            voice_client=voice_client,
            moved=True,
        )

    return MusicVoiceClientResult(voice_client=voice_client)
