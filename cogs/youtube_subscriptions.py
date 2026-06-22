from __future__ import annotations

import math

import discord
from discord import app_commands
from discord.ext import commands

from util.channel_settings import get_channel
from util.youtube.channel_resolver import resolve_youtube_channel_input
from util.youtube_subscriptions import (
    YouTubeSubscription,
    create_youtube_subscription,
    delete_youtube_subscription,
    list_youtube_subscriptions,
    update_youtube_community_notification_state,
    update_youtube_subscription_alert_settings,
)
from util.youtube_community import fetch_latest_youtube_community_posts


YOUTUBE_CHANNEL_TYPE = "youtube"


class YouTubeSubscriptionDeleteSelect(discord.ui.Select):
    def __init__(self, view: "YouTubeSubscriptionDeleteView"):
        start = view.page * view.page_size
        end = start + view.page_size
        page_items = view.subscriptions[start:end]
        options = [
            discord.SelectOption(
                label=subscription.channel_name[:100],
                value=str(subscription.id),
                description=_format_subscription_alert_summary(subscription)[:100],
            )
            for subscription in page_items
        ]
        super().__init__(
            placeholder="삭제할 유튜브 구독을 선택해 주세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, YouTubeSubscriptionDeleteView):
            return
        await parent.delete_selected(interaction, int(self.values[0]))


class YouTubeSubscriptionDeleteView(discord.ui.View):
    def __init__(
        self,
        *,
        requester_id: int,
        guild_id: int,
        subscriptions: list[YouTubeSubscription],
        bot: commands.Bot,
    ):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.guild_id = guild_id
        self.subscriptions = subscriptions
        self.bot = bot
        self.page = 0
        self.page_size = 25
        self._refresh_items()

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(len(self.subscriptions) / self.page_size))

    def _refresh_items(self) -> None:
        self.clear_items()
        if not self.subscriptions:
            return
        self.add_item(YouTubeSubscriptionDeleteSelect(self))
        if self.page_count <= 1:
            return

        previous_button = discord.ui.Button(
            label="이전",
            style=discord.ButtonStyle.secondary,
            disabled=self.page == 0,
        )
        next_button = discord.ui.Button(
            label="다음",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= self.page_count - 1,
        )

        async def previous_callback(interaction: discord.Interaction) -> None:
            if not await self._check_requester(interaction):
                return
            self.page = max(0, self.page - 1)
            self._refresh_items()
            await interaction.response.edit_message(
                content=self._content(),
                view=self,
            )

        async def next_callback(interaction: discord.Interaction) -> None:
            if not await self._check_requester(interaction):
                return
            self.page = min(self.page_count - 1, self.page + 1)
            self._refresh_items()
            await interaction.response.edit_message(
                content=self._content(),
                view=self,
            )

        previous_button.callback = previous_callback
        next_button.callback = next_callback
        self.add_item(previous_button)
        self.add_item(next_button)

    def _content(self) -> str:
        return (
            f"삭제할 유튜브 구독을 선택해 주세요. "
            f"({self.page + 1}/{self.page_count})"
        )

    async def _check_requester(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            "이 삭제 메뉴는 명령어를 실행한 사용자만 조작할 수 있습니다.",
            ephemeral=True,
        )
        return False

    async def delete_selected(
        self,
        interaction: discord.Interaction,
        subscription_id: int,
    ) -> None:
        if not await self._check_requester(interaction):
            return

        deleted = await delete_youtube_subscription(self.guild_id, subscription_id)
        if deleted is None:
            await interaction.response.send_message(
                "삭제할 구독을 찾지 못했습니다. 목록을 새로고침해 주세요.",
                ephemeral=True,
            )
            return

        loop_cog = self.bot.get_cog("LoopTasks")
        if loop_cog and hasattr(loop_cog, "unsubscribe_youtube_websub_subscription"):
            await loop_cog.unsubscribe_youtube_websub_subscription(deleted)

        self.subscriptions = [
            subscription
            for subscription in self.subscriptions
            if subscription.id != subscription_id
        ]
        if self.page >= self.page_count:
            self.page = self.page_count - 1
        self._refresh_items()

        if not self.subscriptions:
            await interaction.response.edit_message(
                content=f"`{deleted.channel_name}` 구독을 삭제했습니다. 남은 구독이 없습니다.",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=f"`{deleted.channel_name}` 구독을 삭제했습니다.\n{self._content()}",
            view=self,
        )


class YouTubeSubscriptionAlertSettingsSelect(discord.ui.Select):
    def __init__(self, view: "YouTubeSubscriptionAlertSettingsView"):
        options = [
            discord.SelectOption(
                label=subscription.channel_name[:100],
                value=str(subscription.id),
                description=_format_subscription_alert_summary(subscription)[:100],
                default=subscription.id == view.selected_subscription_id,
            )
            for subscription in view.subscriptions[:25]
        ]
        super().__init__(
            placeholder="알림 설정을 바꿀 유튜브 구독을 선택해 주세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, YouTubeSubscriptionAlertSettingsView):
            return
        if not await parent._check_requester(interaction):
            return
        parent.selected_subscription_id = int(self.values[0])
        parent._refresh_items()
        await interaction.response.edit_message(
            content=parent._content(),
            view=parent,
        )


class YouTubeSubscriptionAlertSettingsView(discord.ui.View):
    def __init__(
        self,
        *,
        requester_id: int,
        subscriptions: list[YouTubeSubscription],
    ):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.subscriptions = subscriptions
        self.selected_subscription_id = subscriptions[0].id if subscriptions else None
        self._refresh_items()

    def _selected_subscription(self) -> YouTubeSubscription | None:
        if self.selected_subscription_id is None:
            return None
        return next(
            (
                subscription
                for subscription in self.subscriptions
                if subscription.id == self.selected_subscription_id
            ),
            None,
        )

    def _refresh_items(self) -> None:
        self.clear_items()
        if not self.subscriptions:
            return
        self.add_item(YouTubeSubscriptionAlertSettingsSelect(self))
        subscription = self._selected_subscription()
        if subscription is None:
            return

        live_button = discord.ui.Button(
            label=f"라이브 알림 {'끄기' if subscription.live_alert_enabled else '켜기'}",
            style=(
                discord.ButtonStyle.danger
                if subscription.live_alert_enabled
                else discord.ButtonStyle.success
            ),
            disabled=subscription.live_alert_enabled
            and not subscription.upload_alert_enabled
            and not subscription.community_alert_enabled,
        )
        upload_button = discord.ui.Button(
            label=f"영상 알림 {'끄기' if subscription.upload_alert_enabled else '켜기'}",
            style=(
                discord.ButtonStyle.danger
                if subscription.upload_alert_enabled
                else discord.ButtonStyle.success
            ),
            disabled=subscription.upload_alert_enabled
            and not subscription.live_alert_enabled
            and not subscription.community_alert_enabled,
        )
        community_button = discord.ui.Button(
            label=f"커뮤니티 알림 {'끄기' if subscription.community_alert_enabled else '켜기'}",
            style=(
                discord.ButtonStyle.danger
                if subscription.community_alert_enabled
                else discord.ButtonStyle.success
            ),
            disabled=subscription.community_alert_enabled
            and not subscription.live_alert_enabled
            and not subscription.upload_alert_enabled,
        )

        async def live_callback(interaction: discord.Interaction) -> None:
            await self._update_selected(
                interaction,
                live_alert_enabled=not subscription.live_alert_enabled,
                upload_alert_enabled=subscription.upload_alert_enabled,
                community_alert_enabled=subscription.community_alert_enabled,
            )

        async def upload_callback(interaction: discord.Interaction) -> None:
            await self._update_selected(
                interaction,
                live_alert_enabled=subscription.live_alert_enabled,
                upload_alert_enabled=not subscription.upload_alert_enabled,
                community_alert_enabled=subscription.community_alert_enabled,
            )

        async def community_callback(interaction: discord.Interaction) -> None:
            await self._update_selected(
                interaction,
                live_alert_enabled=subscription.live_alert_enabled,
                upload_alert_enabled=subscription.upload_alert_enabled,
                community_alert_enabled=not subscription.community_alert_enabled,
            )

        live_button.callback = live_callback
        upload_button.callback = upload_callback
        community_button.callback = community_callback
        self.add_item(live_button)
        self.add_item(upload_button)
        self.add_item(community_button)

    def _content(self) -> str:
        subscription = self._selected_subscription()
        if subscription is None:
            return "알림 설정을 바꿀 유튜브 구독을 선택해 주세요."
        return (
            f"`{subscription.channel_name}` 알림 설정\n"
            f"{_format_subscription_alert_summary(subscription)}\n"
            "라이브 알림, 영상 알림, 커뮤니티 알림 중 하나 이상은 켜져 있어야 합니다."
        )

    async def _check_requester(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            "이 알림 설정 메뉴는 명령어를 실행한 사용자만 조작할 수 있습니다.",
            ephemeral=True,
        )
        return False

    async def _update_selected(
        self,
        interaction: discord.Interaction,
        *,
        live_alert_enabled: bool,
        upload_alert_enabled: bool,
        community_alert_enabled: bool,
    ) -> None:
        if not await self._check_requester(interaction):
            return
        if self.selected_subscription_id is None:
            await interaction.response.send_message(
                "설정할 구독을 찾지 못했습니다. 목록을 새로 열어 주세요.",
                ephemeral=True,
            )
            return

        try:
            updated = await update_youtube_subscription_alert_settings(
                self.selected_subscription_id,
                live_alert_enabled=live_alert_enabled,
                upload_alert_enabled=upload_alert_enabled,
                community_alert_enabled=community_alert_enabled,
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        if updated is None:
            await interaction.response.send_message(
                "설정할 구독을 찾지 못했습니다. 목록을 새로 열어 주세요.",
                ephemeral=True,
            )
            return

        if community_alert_enabled and not subscription.community_alert_enabled:
            try:
                latest_posts = await fetch_latest_youtube_community_posts(
                    updated.channel_id
                )
                notified_post_ids = [post.post_id for post in latest_posts]
                await update_youtube_community_notification_state(
                    updated.id,
                    notified_community_post_ids=notified_post_ids,
                )
                updated = await update_youtube_subscription_alert_settings(
                    updated.id,
                    live_alert_enabled=updated.live_alert_enabled,
                    upload_alert_enabled=updated.upload_alert_enabled,
                    community_alert_enabled=updated.community_alert_enabled,
                )
            except Exception as error:
                print(
                    "유튜브 커뮤니티 초기 게시물 상태 저장 실패: "
                    f"channel={updated.channel_id} error={error}"
                )

        self.subscriptions = [
            updated if subscription.id == updated.id else subscription
            for subscription in self.subscriptions
        ]
        self._refresh_items()
        await interaction.response.edit_message(
            content=self._content(),
            view=self,
        )


class YouTubeSubscriptionsCog(commands.Cog):
    youtube_subscription = app_commands.Group(
        name="유튜브구독",
        description="서버별 유튜브 라이브/영상/커뮤니티 알림 구독을 관리합니다.",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _require_guild_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "이 명령어는 길드에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "길드 멤버만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message(
            "관리자 권한이 있는 사용자만 유튜브 구독을 관리할 수 있습니다.",
            ephemeral=True,
        )
        return False

    @youtube_subscription.command(
        name="추가",
        description="유튜브 채널 URL, ID, @handle 또는 검색어로 구독을 추가합니다.",
    )
    @app_commands.describe(
        input_value="유튜브 채널 URL, ID, @handle 또는 검색어",
        live_alert_enabled="라이브 시작 알림을 받을지 선택합니다. 기본값은 켜짐입니다.",
        upload_alert_enabled="새 영상 업로드 알림을 받을지 선택합니다. 기본값은 꺼짐입니다.",
        community_alert_enabled="새 커뮤니티 게시물 알림을 받을지 선택합니다. 기본값은 꺼짐입니다.",
    )
    @app_commands.rename(
        input_value="입력",
        live_alert_enabled="라이브알림",
        upload_alert_enabled="영상알림",
        community_alert_enabled="커뮤니티알림",
    )
    async def add_subscription(
        self,
        interaction: discord.Interaction,
        input_value: str,
        live_alert_enabled: bool = True,
        upload_alert_enabled: bool = False,
        community_alert_enabled: bool = False,
    ) -> None:
        if not await self._require_guild_admin(interaction):
            return
        if not live_alert_enabled and not upload_alert_enabled and not community_alert_enabled:
            await interaction.response.send_message(
                "라이브 알림, 영상 알림, 커뮤니티 알림 중 하나 이상을 켜야 합니다.",
                ephemeral=False,
            )
            return
        guild_id = int(interaction.guild_id)
        target_channel_id = await get_channel(guild_id, YOUTUBE_CHANNEL_TYPE)
        if target_channel_id is None:
            await interaction.response.send_message(
                "`/채널설정 기능:유튜브 채널:#알림채널`을 먼저 설정해 주세요.",
                ephemeral=False,
            )
            return

        await interaction.response.defer(ephemeral=False, thinking=True)
        try:
            metadata = await resolve_youtube_channel_input(input_value)
            initial_community_post_ids = []
            if community_alert_enabled:
                latest_posts = await fetch_latest_youtube_community_posts(
                    metadata.channel_id
                )
                initial_community_post_ids = [post.post_id for post in latest_posts]
            subscription_id = await create_youtube_subscription(
                guild_id=guild_id,
                channel_name=metadata.channel_name,
                channel_id=metadata.channel_id,
                channel_handle=metadata.channel_handle,
                source_input=input_value.strip(),
                live_alert_enabled=live_alert_enabled,
                upload_alert_enabled=upload_alert_enabled,
                community_alert_enabled=community_alert_enabled,
                notified_community_post_ids=initial_community_post_ids,
            )
            loop_cog = self.bot.get_cog("LoopTasks")
            websub_required = live_alert_enabled or upload_alert_enabled
            subscribed = not websub_required
            if (
                websub_required
                and loop_cog
                and hasattr(loop_cog, "ensure_youtube_websub_subscription")
            ):
                subscribed = await loop_cog.ensure_youtube_websub_subscription(
                    subscription_id
                )

            message = (
                f"`{metadata.channel_name}` 구독을 추가했습니다.\n"
                f"채널 ID: `{metadata.channel_id}`\n"
                f"알림 채널: <#{target_channel_id}>\n"
                f"라이브 알림: {_format_alert_enabled(live_alert_enabled)} / "
                f"영상 알림: {_format_alert_enabled(upload_alert_enabled)} / "
                f"커뮤니티 알림: {_format_alert_enabled(community_alert_enabled)}"
            )
            if not subscribed:
                message += "\n⚠️ WebSub callback 설정을 확인해 주세요."
            await interaction.followup.send(message, ephemeral=False)
        except Exception as error:
            await interaction.followup.send(f"오류: {error}", ephemeral=False)

    @youtube_subscription.command(
        name="알림설정",
        description="유튜브 구독별 라이브 알림과 영상 알림을 켜거나 끕니다.",
    )
    async def configure_subscription_alerts(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not await self._require_guild_admin(interaction):
            return
        guild_id = int(interaction.guild_id)
        subscriptions = await list_youtube_subscriptions(guild_id)
        if not subscriptions:
            await interaction.response.send_message(
                "등록된 유튜브 구독이 없습니다.",
                ephemeral=False,
            )
            return

        view = YouTubeSubscriptionAlertSettingsView(
            requester_id=interaction.user.id,
            subscriptions=subscriptions,
        )
        await interaction.response.send_message(
            view._content(),
            view=view,
            ephemeral=False,
        )

    @youtube_subscription.command(
        name="삭제",
        description="서버의 유튜브 구독 목록에서 선택한 채널을 삭제합니다.",
    )
    async def delete_subscription(self, interaction: discord.Interaction) -> None:
        if not await self._require_guild_admin(interaction):
            return
        guild_id = int(interaction.guild_id)
        subscriptions = await list_youtube_subscriptions(guild_id)
        if not subscriptions:
            await interaction.response.send_message(
                "등록된 유튜브 구독이 없습니다.",
                ephemeral=False,
            )
            return

        view = YouTubeSubscriptionDeleteView(
            requester_id=interaction.user.id,
            guild_id=guild_id,
            subscriptions=subscriptions,
            bot=self.bot,
        )
        await interaction.response.send_message(
            view._content(),
            view=view,
            ephemeral=False,
        )

    @youtube_subscription.command(
        name="목록",
        description="서버의 유튜브 구독 목록을 보여줍니다.",
    )
    async def list_subscription(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "이 명령어는 길드에서만 사용할 수 있습니다.",
                ephemeral=False,
            )
            return

        guild_id = int(interaction.guild_id)
        subscriptions = await list_youtube_subscriptions(guild_id)
        target_channel_id = await get_channel(guild_id, YOUTUBE_CHANNEL_TYPE)
        embed = discord.Embed(
            title="📺 유튜브 구독 목록",
            color=discord.Color.red(),
        )
        embed.add_field(
            name="알림 채널",
            value=f"<#{target_channel_id}>" if target_channel_id else "미지정",
            inline=False,
        )

        if not subscriptions:
            embed.description = "등록된 유튜브 구독이 없습니다."
        else:
            lines = [
                _format_subscription_line(index, subscription)
                for index, subscription in enumerate(subscriptions, start=1)
            ]
            embed.description = "\n".join(lines[:30])
            if len(lines) > 30:
                embed.set_footer(text=f"총 {len(lines)}개 중 30개만 표시합니다.")

        await interaction.response.send_message(embed=embed, ephemeral=False)


def _format_subscription_line(
    index: int,
    subscription: YouTubeSubscription,
) -> str:
    handle = f" ({subscription.channel_handle})" if subscription.channel_handle else ""
    return (
        f"{index}. **{subscription.channel_name}**{handle}\n"
        f"   `{subscription.channel_id}`\n"
        f"   {_format_subscription_alert_summary(subscription)}"
    )


def _format_alert_enabled(enabled: bool) -> str:
    return "ON" if enabled else "OFF"


def _format_subscription_alert_summary(subscription: YouTubeSubscription) -> str:
    return (
        f"라이브: {_format_alert_enabled(subscription.live_alert_enabled)} / "
        f"영상: {_format_alert_enabled(subscription.upload_alert_enabled)} / "
        f"커뮤니티: {_format_alert_enabled(subscription.community_alert_enabled)}"
    )


async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeSubscriptionsCog(bot))
    print("YouTubeSubscriptionsCog : setup 완료!")
