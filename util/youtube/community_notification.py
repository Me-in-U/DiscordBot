from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace

import discord

from util.guild.channel_settings import get_channel
from util.youtube.community import (
    YouTubeCommunityPost,
    find_new_youtube_community_posts,
    trim_notified_community_post_ids,
)
from util.youtube.notification_sender import (
    GetChannelSetting,
    resolve_youtube_notification_target,
)
from util.youtube.subscriptions import (
    YouTubeSubscription,
    update_youtube_community_notification_state,
)


UpdateCommunityState = Callable[..., Awaitable[None]]


async def mark_youtube_community_post_notified(
    subscription: YouTubeSubscription,
    post_id: str,
    *,
    update_community_state: UpdateCommunityState = (
        update_youtube_community_notification_state
    ),
) -> YouTubeSubscription:
    notified_ids = [str(current_id) for current_id in subscription.notified_community_post_ids]
    if post_id not in notified_ids:
        notified_ids.append(post_id)
    notified_ids = trim_notified_community_post_ids(notified_ids)
    await update_community_state(
        subscription.id,
        notified_community_post_ids=notified_ids,
    )
    return replace(subscription, notified_community_post_ids=notified_ids)


async def send_youtube_community_notification(
    bot,
    subscription: YouTubeSubscription,
    post: YouTubeCommunityPost,
    *,
    get_channel_setting: GetChannelSetting = get_channel,
) -> bool:
    if post.post_id in _notified_community_post_id_set(subscription):
        return False

    target = await _resolve_community_notification_target(
        bot,
        subscription,
        get_channel_setting=get_channel_setting,
    )
    if target is None:
        return False

    await target.send(
        content=f"## 📝 {subscription.channel_name} 새 커뮤니티 게시물\n{post.url}",
        embed=_build_youtube_community_embed(subscription, post),
    )
    return True


async def process_youtube_community_notifications(
    bot,
    subscription: YouTubeSubscription,
    posts: Sequence[YouTubeCommunityPost],
    *,
    get_channel_setting: GetChannelSetting = get_channel,
    update_community_state: UpdateCommunityState = (
        update_youtube_community_notification_state
    ),
) -> YouTubeSubscription:
    if not subscription.community_alert_enabled or not posts:
        return subscription

    if not subscription.notified_community_post_ids:
        notified_ids = trim_notified_community_post_ids(
            [post.post_id for post in posts]
        )
        await update_community_state(
            subscription.id,
            notified_community_post_ids=notified_ids,
        )
        return replace(subscription, notified_community_post_ids=notified_ids)

    new_posts = find_new_youtube_community_posts(
        list(posts),
        subscription.notified_community_post_ids,
    )
    for post in reversed(new_posts):
        sent = await send_youtube_community_notification(
            bot,
            subscription,
            post,
            get_channel_setting=get_channel_setting,
        )
        if sent:
            subscription = await mark_youtube_community_post_notified(
                subscription,
                post.post_id,
                update_community_state=update_community_state,
            )

    return subscription


async def _resolve_community_notification_target(
    bot,
    subscription: YouTubeSubscription,
    *,
    get_channel_setting: GetChannelSetting,
):
    return await resolve_youtube_notification_target(
        bot,
        subscription,
        "커뮤니티",
        get_channel_setting=get_channel_setting,
    )


def _notified_community_post_id_set(subscription: YouTubeSubscription) -> set[str]:
    return {
        str(post_id)
        for post_id in subscription.notified_community_post_ids
        if post_id
    }


def _build_youtube_community_embed(
    subscription: YouTubeSubscription,
    post: YouTubeCommunityPost,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{subscription.channel_name} 커뮤니티 게시물",
        description=_truncate_discord_text(post.text or "본문 없음", 900),
        url=post.url,
        color=discord.Color.red(),
    )
    if post.author:
        embed.set_author(name=post.author)
    if post.published_time:
        embed.add_field(name="게시 시각", value=post.published_time, inline=True)
    if post.attachment_urls:
        embed.set_image(url=post.attachment_urls[0])
    return embed


def _truncate_discord_text(text: str, max_length: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."
