from __future__ import annotations

import math

import discord
from discord import app_commands
from discord.ext import commands

from util.celebration.dday import (
    DdayEvent,
    build_dday_list_embed,
    calculate_dday_label,
    create_dday_event,
    delete_dday_event,
    list_dday_events,
    parse_dday_date,
)


class DdayDeleteSelect(discord.ui.Select):
    def __init__(self, view: "DdayDeleteView"):
        start = view.page * view.page_size
        end = start + view.page_size
        page_items = view.events[start:end]
        options = [
            discord.SelectOption(
                label=event.title[:100],
                value=str(event.id),
                description=(
                    f"{event.target_date.isoformat()} · "
                    f"{calculate_dday_label(event.target_date)}"
                )[:100],
            )
            for event in page_items
        ]
        super().__init__(
            placeholder="삭제할 DDAY를 선택해 주세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, DdayDeleteView):
            return
        await parent.delete_selected(interaction, int(self.values[0]))


class DdayDeleteView(discord.ui.View):
    def __init__(
        self,
        *,
        requester_id: int,
        guild_id: int,
        events: list[DdayEvent],
    ):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.guild_id = guild_id
        self.events = events
        self.page = 0
        self.page_size = 25
        self._refresh_items()

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(len(self.events) / self.page_size))

    def _refresh_items(self) -> None:
        self.clear_items()
        if not self.events:
            return
        self.add_item(DdayDeleteSelect(self))
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
        return f"삭제할 DDAY를 선택해 주세요. ({self.page + 1}/{self.page_count})"

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
        event_id: int,
    ) -> None:
        if not await self._check_requester(interaction):
            return

        deleted = await delete_dday_event(self.guild_id, event_id)
        if deleted is None:
            await interaction.response.send_message(
                "삭제할 DDAY를 찾지 못했습니다. 목록을 새로고침해 주세요.",
                ephemeral=True,
            )
            return

        self.events = [event for event in self.events if event.id != event_id]
        if self.page >= self.page_count:
            self.page = self.page_count - 1
        self._refresh_items()

        if not self.events:
            await interaction.response.edit_message(
                content=f"`{deleted.title}` DDAY를 삭제했습니다. 남은 DDAY가 없습니다.",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=f"`{deleted.title}` DDAY를 삭제했습니다.\n{self._content()}",
            view=self,
        )


class DdayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _require_guild(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is not None:
            return True
        await interaction.response.send_message(
            "이 명령어는 길드에서만 사용할 수 있습니다.",
            ephemeral=True,
        )
        return False

    @app_commands.command(
        name="dday추가",
        description="서버 DDAY를 추가합니다.",
    )
    @app_commands.describe(
        date_text="DDAY 날짜. 예: 2026-06-04, 2026.06.04, 2026/06/04, 20260604",
        title="DDAY 제목",
        show_after="날짜가 지난 뒤에도 D+N으로 자동 공지에 표시합니다.",
    )
    @app_commands.rename(
        date_text="날짜",
        title="제목",
        show_after="지난날짜표시",
    )
    async def add_dday(
        self,
        interaction: discord.Interaction,
        date_text: str,
        title: str,
        show_after: bool = False,
    ) -> None:
        if not await self._require_guild(interaction):
            return

        try:
            target_date = parse_dday_date(date_text)
            event_id = await create_dday_event(
                guild_id=int(interaction.guild_id),
                title=title,
                target_date=target_date,
                show_after=show_after,
                created_by=int(interaction.user.id),
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        label = calculate_dday_label(target_date)
        embed = discord.Embed(
            title="📅 DDAY 추가 완료",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="제목", value=title.strip(), inline=False)
        embed.add_field(name="날짜", value=target_date.isoformat(), inline=True)
        embed.add_field(name="DDAY", value=label, inline=True)
        embed.add_field(
            name="지난 날짜 표시",
            value="ON" if show_after else "OFF",
            inline=True,
        )
        embed.set_footer(text=f"ID: {event_id}")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(
        name="dday삭제",
        description="서버 DDAY 목록에서 선택한 항목을 삭제합니다.",
    )
    async def delete_dday(self, interaction: discord.Interaction) -> None:
        if not await self._require_guild(interaction):
            return

        events = await list_dday_events(int(interaction.guild_id))
        if not events:
            await interaction.response.send_message(
                "등록된 DDAY가 없습니다.",
                ephemeral=False,
            )
            return

        view = DdayDeleteView(
            requester_id=interaction.user.id,
            guild_id=int(interaction.guild_id),
            events=events,
        )
        await interaction.response.send_message(
            view._content(),
            view=view,
            ephemeral=False,
        )

    @app_commands.command(
        name="dday목록",
        description="서버 DDAY 목록을 보여줍니다.",
    )
    async def list_dday(self, interaction: discord.Interaction) -> None:
        if not await self._require_guild(interaction):
            return

        events = await list_dday_events(int(interaction.guild_id))
        await interaction.response.send_message(
            embed=build_dday_list_embed(events),
            ephemeral=False,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(DdayCog(bot))
    print("DdayCog : setup 완료!")
