from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from util.guild.channel_settings import get_channel
from util.youtube.subscriptions import YouTubeSubscription
from util.youtube.websub import (
    YouTubeVideoLiveStatus,
    build_youtube_live_notification_message,
    build_youtube_upload_notification_message,
)


YOUTUBE_CHANNEL_TYPE = "youtube"

GetChannelSetting = Callable[[int, str], Awaitable[int | None]]
LogMessage = Callable[[str], None]


async def resolve_youtube_notification_target(
    bot,
    subscription: YouTubeSubscription,
    alert_label: str,
    *,
    get_channel_setting: GetChannelSetting = get_channel,
    log: LogMessage = print,
):
    target_channel_id = await get_channel_setting(
        subscription.guild_id,
        YOUTUBE_CHANNEL_TYPE,
    )
    if target_channel_id is None:
        log(
            f"YouTube {alert_label} 알림 채널이 설정되지 않았습니다. "
            f"guild={subscription.guild_id} channel={subscription.channel_id}"
        )
        return None

    target = bot.get_channel(target_channel_id)
    if target is None:
        try:
            target = await bot.fetch_channel(target_channel_id)
        except discord.DiscordException:
            log(
                f"YouTube {alert_label} 알림 대상 채널을 찾을 수 없습니다. "
                f"guild={subscription.guild_id} channel_id={target_channel_id}"
            )
            return None

    return target


async def send_youtube_live_notification(
    bot,
    subscription: YouTubeSubscription,
    status: YouTubeVideoLiveStatus,
    *,
    get_channel_setting: GetChannelSetting = get_channel,
    log: LogMessage = print,
) -> bool:
    if status.video_id in {str(video_id) for video_id in subscription.notified_video_ids if video_id}:
        return False

    target = await resolve_youtube_notification_target(
        bot,
        subscription,
        "라이브",
        get_channel_setting=get_channel_setting,
        log=log,
    )
    if target is None:
        return False

    await target.send(build_youtube_live_notification_message(status.video_id))
    return True


async def send_youtube_upload_notification(
    bot,
    subscription: YouTubeSubscription,
    status: YouTubeVideoLiveStatus,
    *,
    get_channel_setting: GetChannelSetting = get_channel,
    log: LogMessage = print,
) -> bool:
    if status.video_id in {
        str(video_id) for video_id in subscription.notified_upload_video_ids if video_id
    }:
        return False

    target = await resolve_youtube_notification_target(
        bot,
        subscription,
        "영상",
        get_channel_setting=get_channel_setting,
        log=log,
    )
    if target is None:
        return False

    await target.send(
        build_youtube_upload_notification_message(
            subscription.channel_name,
            status.title,
            status.video_id,
        )
    )
    return True
