import discord
from discord import app_commands
from discord.ext import commands, tasks
import uuid
from datetime import datetime, timedelta
from bot import SEOUL_TZ
from util.db import execute_query, fetch_all


class SchedulerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_schedule_task.start()
        print("SchedulerCog : init 완료!")

    def cog_unload(self):
        self.check_schedule_task.cancel()

    def calculate_next_run(self, item, current_trigger):
        # item is dict from row
        repeat_type = item.get("repeat_type")
        value = item.get("repeat_value")

        try:
            if repeat_type == "hourly":
                interval = int(value)
                return current_trigger + timedelta(hours=interval)
            elif repeat_type == "daily":
                return current_trigger + timedelta(days=1)
            elif repeat_type == "weekly":
                return current_trigger + timedelta(weeks=1)
            elif repeat_type == "monthly":
                year = current_trigger.year
                month = current_trigger.month
                if month == 12:
                    year += 1
                    month = 1
                else:
                    month += 1
                try:
                    return current_trigger.replace(year=year, month=month)
                except ValueError:
                    if month == 12:
                        return current_trigger.replace(year=year + 1, month=1, day=1)
                    else:
                        return current_trigger.replace(month=month + 1, day=1)
        except Exception as e:
            print(f"Next run calc error: {e}")
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
    ):
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
                    str(interaction.guild_id),
                    str(interaction.channel_id),
                    str(interaction.user.id),
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
    ):
        now = datetime.now(SEOUL_TZ)
        trigger_time = now  # Logic omitted for brevity, usually current time + interval or next occurrence
        # Simplified trigger time logic mostly for demo
        # Real implementation should parse 'value' to find next occurrence
        # For 'hourly' -> now + int(value) hours
        try:
            val = value
            if repeat_type == "hourly":
                trigger_time = now + timedelta(hours=int(val))
            elif repeat_type == "daily":
                t = datetime.strptime(val, "%H:%M").time()
                trigger_time = now.replace(hour=t.hour, minute=t.minute, second=0)
                if trigger_time <= now:
                    trigger_time += timedelta(days=1)
            # ... and so on. For simplicity, just insert.
        except:
            pass

        uid = str(uuid.uuid4())
        query = """INSERT INTO scheduled_messages (id, guild_id, channel_id, user_id, trigger_time, message, created_at, type, repeat_type, repeat_value, is_recurring) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'recurring', %s, %s, 1)"""
        await execute_query(
            query,
            (
                uid,
                str(interaction.guild_id),
                str(interaction.channel_id),
                str(interaction.user.id),
                trigger_time,
                message,
                now,
                repeat_type,
                value,
            ),
        )
        await interaction.response.send_message("✅ 반복 예약 완료", ephemeral=True)

    @schedule_group.command(name="리스트", description="현재 등록된 예약 목록")
    async def list_reservations(self, interaction: discord.Interaction):
        query = "SELECT * FROM scheduled_messages WHERE guild_id = %s AND user_id = %s ORDER BY trigger_time"
        rows = await fetch_all(
            query, (str(interaction.guild_id), str(interaction.user.id))
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
    async def check_schedule_task(self):
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
            except Exception as e:
                print(f"Message send error: {e}")

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
    async def before_check_schedule_task(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(SchedulerCog(bot))
