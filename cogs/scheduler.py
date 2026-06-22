from __future__ import annotations

import logging
from typing import Any, TypedDict

import discord
from discord import app_commands
from discord.ext import commands, tasks
import uuid
from datetime import datetime, timedelta
from bot import SEOUL_TZ
from util.db import execute_query, fetch_all

logger = logging.getLogger(__name__)


class ScheduledMessageRow(TypedDict, total=False):
    id: str
    guild_id: int
    channel_id: int
    user_id: int
    trigger_time: datetime
    message: str
    type: str
    repeat_type: str | None
    repeat_value: str | None
    is_recurring: bool


def calculate_recurring_trigger_time(
    now: datetime,
    repeat_type: str,
    value: str,
) -> datetime:
    if repeat_type == "hourly":
        try:
            interval = int(value)
        except ValueError as exc:
            raise ValueError("hourly 반복 값은 양의 정수여야 합니다.") from exc
        if interval <= 0:
            raise ValueError("hourly 반복 값은 양의 정수여야 합니다.")
        return now + timedelta(hours=interval)

    if repeat_type == "daily":
        trigger_time_value = datetime.strptime(value, "%H:%M").time()
        trigger_time = now.replace(
            hour=trigger_time_value.hour,
            minute=trigger_time_value.minute,
            second=0,
            microsecond=0,
        )
        if trigger_time <= now:
            trigger_time += timedelta(days=1)
        return trigger_time

    if repeat_type == "weekly":
        return now + timedelta(weeks=1)

    if repeat_type == "monthly":
        year = now.year
        month = now.month + 1
        if month > 12:
            year += 1
            month = 1
        try:
            return now.replace(year=year, month=month)
        except ValueError:
            if month == 12:
                return now.replace(year=year + 1, month=1, day=1)
            return now.replace(year=year, month=month + 1, day=1)

    raise ValueError(f"지원하지 않는 반복 유형입니다: {repeat_type}")


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.check_schedule_task.start()
        print("SchedulerCog : init 완료!")

    def cog_unload(self) -> None:
        self.check_schedule_task.cancel()

    def calculate_next_run(
        self,
        item: ScheduledMessageRow | dict[str, Any],
        current_trigger: datetime,
    ) -> datetime | None:
        # item is dict from row
        repeat_type = item.get("repeat_type")
        value = item.get("repeat_value")

        if not repeat_type or value is None:
            return None
        try:
            if repeat_type == "daily":
                return current_trigger + timedelta(days=1)
            return calculate_recurring_trigger_time(current_trigger, repeat_type, str(value))
        except ValueError:
            logger.warning("Next run calc error: item=%s", item, exc_info=True)
            return None
        return None

    schedule_group = app_commands.Group(name="예약", description="예약 메시지 관리")

    @schedule_group.command(
        name="일반", description="지정된 날짜와 시간에 메시지를 예약합니다."
    )
    @app_commands.describe(
        date="날짜 (YYYY-MM-DD 또는 MM-DD)",
        time_str="시간 (HH:MM, 24시간제)",
        message="전송할 메시지",
    )
    async def add_one_time(
        self, interaction: discord.Interaction, date: str, time_str: str, message: str
    ) -> None:
        current_year = datetime.now(SEOUL_TZ).year
        if len(date.split("-")) == 2:
            date = f"{current_year}-{date}"
        try:
            target_dt = datetime.strptime(
                f"{date} {time_str}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=SEOUL_TZ)
            now = datetime.now(SEOUL_TZ)
            if target_dt <= now:
                await interaction.response.send_message(
                    "❌ 과거의 시간으로는 예약할 수 없습니다.", ephemeral=True
                )
                return

            uid = str(uuid.uuid4())
            query = """INSERT INTO scheduled_messages (id, guild_id, channel_id, user_id, trigger_time, message, created_at, type) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'one-time')"""
            await execute_query(
                query,
                (
                    uid,
                    int(interaction.guild_id),
                    int(interaction.channel_id),
                    int(interaction.user.id),
                    target_dt,
                    message,
                    now,
                ),
            )

            await interaction.response.send_message(
                f"✅ 예약 완료!\n📅 일시: {target_dt}\n💬 메시지: {message}",
                ephemeral=True,
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ 날짜/시간 형식이 올바르지 않습니다.", ephemeral=True
            )

    @schedule_group.command(name="반복", description="주기적으로 반복되는 메시지 예약")
    @app_commands.choices(
        repeat_type=[
            app_commands.Choice(name="매시간", value="hourly"),
            app_commands.Choice(name="매일", value="daily"),
            app_commands.Choice(name="매주", value="weekly"),
            app_commands.Choice(name="매달", value="monthly"),
        ]
    )
    async def add_recurring(
        self,
        interaction: discord.Interaction,
        repeat_type: str,
        value: str,
        message: str,
    ) -> None:
        now = datetime.now(SEOUL_TZ)
        try:
            trigger_time = calculate_recurring_trigger_time(now, repeat_type, value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ 반복 예약 값이 올바르지 않습니다. {exc}", ephemeral=True)
            return

        uid = str(uuid.uuid4())
        query = """INSERT INTO scheduled_messages (id, guild_id, channel_id, user_id, trigger_time, message, created_at, type, repeat_type, repeat_value, is_recurring) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'recurring', %s, %s, 1)"""
        await execute_query(
            query,
            (
                uid,
                int(interaction.guild_id),
                int(interaction.channel_id),
                int(interaction.user.id),
                trigger_time,
                message,
                now,
                repeat_type,
                value,
            ),
        )
        await interaction.response.send_message("✅ 반복 예약 완료", ephemeral=True)

    @schedule_group.command(name="리스트", description="현재 등록된 예약 목록")
    async def list_reservations(self, interaction: discord.Interaction) -> None:
        query = "SELECT * FROM scheduled_messages WHERE guild_id = %s AND user_id = %s ORDER BY trigger_time"
        rows = await fetch_all(
            query, (int(interaction.guild_id), int(interaction.user.id))
        )
        if not rows:
            await interaction.response.send_message("📭 예약 없음", ephemeral=True)
            return

        desc = ""
        for idx, row in enumerate(rows):
            desc += f"{idx+1}. {row['trigger_time']} | {row['message'][:20]}\n"

        embed = discord.Embed(
            title="예약 목록", description=desc, color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tasks.loop(seconds=30)
    async def check_schedule_task(self) -> None:
        now = datetime.now(SEOUL_TZ)
        query = "SELECT * FROM scheduled_messages WHERE trigger_time <= %s"
        rows = await fetch_all(query, (now,))

        if not rows:
            return

        for row in rows:
            try:
                channel = self.bot.get_channel(int(row["channel_id"]))
                if channel:
                    prefix = "🔄" if row["is_recurring"] else "⏰"
                    await channel.send(
                        f"{prefix} 예약 메시지 (<@{row['user_id']}>):\n{row['message']}"
                    )
            except Exception:
                logger.exception("Message send error: row=%s", row)

            if row["is_recurring"]:
                next_run = self.calculate_next_run(row, row["trigger_time"])
                if next_run:
                    await execute_query(
                        "UPDATE scheduled_messages SET trigger_time = %s WHERE id = %s",
                        (next_run, row["id"]),
                    )
                else:
                    await execute_query(
                        "DELETE FROM scheduled_messages WHERE id = %s", (row["id"],)
                    )
            else:
                await execute_query(
                    "DELETE FROM scheduled_messages WHERE id = %s", (row["id"],)
                )

    @check_schedule_task.before_loop
    async def before_check_schedule_task(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
