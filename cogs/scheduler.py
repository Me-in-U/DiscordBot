import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import uuid
from datetime import datetime, timedelta
from bot import SEOUL_TZ

SCHEDULER_FILE = "message_scheduler.json"


class SchedulerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.schedules = self.load_schedules()
        self.check_schedule_task.start()
        print("SchedulerCog : init 완료!")

    def cog_unload(self):
        self.check_schedule_task.cancel()

    def load_schedules(self):
        if not os.path.exists(SCHEDULER_FILE):
            return []
        try:
            with open(SCHEDULER_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else []
        except Exception as e:
            print(f"스케줄 로드 실패: {e}")
            return []

    def save_schedules(self):
        try:
            with open(SCHEDULER_FILE, "w", encoding="utf-8") as f:
                json.dump(self.schedules, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"스케줄 저장 실패: {e}")

    # 예약 명령어 그룹 생성
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
        # 날짜 포맷 처리
        current_year = datetime.now(SEOUL_TZ).year

        # MM-DD 형식인 경우 연도 추가
        if len(date.split("-")) == 2:
            date = f"{current_year}-{date}"

        try:
            target_dt_str = f"{date} {time_str}"
            target_dt = datetime.strptime(target_dt_str, "%Y-%m-%d %H:%M")
            target_dt = target_dt.replace(tzinfo=SEOUL_TZ)

            now = datetime.now(SEOUL_TZ)
            if target_dt <= now:
                await interaction.response.send_message(
                    "❌ 과거의 시간으로는 예약할 수 없습니다.", ephemeral=True
                )
                return

            if target_dt - now < timedelta(minutes=1):
                await interaction.response.send_message(
                    "❌ 예약은 현재 시간으로부터 최소 1분 이상 후로 설정해야 합니다.",
                    ephemeral=True,
                )
                return

            schedule_item = {
                "id": str(uuid.uuid4()),
                "guild_id": interaction.guild_id,
                "channel_id": interaction.channel_id,
                "user_id": interaction.user.id,
                "trigger_time": target_dt.isoformat(),
                "message": message,
                "created_at": now.isoformat(),
                "type": "one-time",
            }

            self.schedules.append(schedule_item)
            self.save_schedules()

            await interaction.response.send_message(
                f"✅ 예약 완료!\n📅 일시: {target_dt.strftime('%Y-%m-%d %H:%M')}\n💬 메시지: {message}",
                ephemeral=True,
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ 날짜/시간 형식이 올바르지 않습니다.\n날짜: YYYY-MM-DD 또는 MM-DD\n시간: HH:MM (24시간제)",
                ephemeral=True,
            )

    @schedule_group.command(
        name="반복", description="주기적으로 반복되는 메시지를 예약합니다."
    )
    @app_commands.describe(
        repeat_type="반복 주기 선택",
        value="설정값 (매시간:시간간격, 매일:HH:MM, 매주:요일 HH:MM, 매달:일 HH:MM)",
        message="전송할 메시지",
    )
    @app_commands.choices(
        repeat_type=[
            app_commands.Choice(name="매시간 (N시간 마다)", value="hourly"),
            app_commands.Choice(name="매일 (매일 HH:MM)", value="daily"),
            app_commands.Choice(name="매주 (매주 요일 HH:MM)", value="weekly"),
            app_commands.Choice(name="매달 (매달 DD일 HH:MM)", value="monthly"),
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
        trigger_time = None

        try:
            if repeat_type == "hourly":
                # value: 시간 간격 (int)
                interval = int(value)
                if interval < 1:
                    raise ValueError("간격은 1시간 이상이어야 합니다.")
                # 시작 시간은 현재 시간 + interval
                trigger_time = now + timedelta(hours=interval)

            elif repeat_type == "daily":
                # value: HH:MM
                target_time = datetime.strptime(value, "%H:%M").time()
                trigger_time = now.replace(
                    hour=target_time.hour,
                    minute=target_time.minute,
                    second=0,
                    microsecond=0,
                )
                if trigger_time <= now:
                    trigger_time += timedelta(days=1)

            elif repeat_type == "weekly":
                # value: 요일 HH:MM (예: 월 13:00, Mon 13:00)
                day_str, time_str = value.split()
                target_time = datetime.strptime(time_str, "%H:%M").time()

                weekdays = ["월", "화", "수", "목", "금", "토", "일"]
                eng_weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

                target_weekday = -1
                if day_str in weekdays:
                    target_weekday = weekdays.index(day_str)
                else:
                    for i, eng in enumerate(eng_weekdays):
                        if day_str.lower().startswith(eng):
                            target_weekday = i
                            break

                if target_weekday == -1:
                    raise ValueError("요일 형식이 올바르지 않습니다.")

                trigger_time = now.replace(
                    hour=target_time.hour,
                    minute=target_time.minute,
                    second=0,
                    microsecond=0,
                )
                current_weekday = trigger_time.weekday()

                days_ahead = target_weekday - current_weekday
                if days_ahead < 0 or (days_ahead == 0 and trigger_time <= now):
                    days_ahead += 7
                trigger_time += timedelta(days=days_ahead)

            elif repeat_type == "monthly":
                # value: DD HH:MM (예: 15 13:00)
                day_str, time_str = value.split()
                day = int(day_str)
                target_time = datetime.strptime(time_str, "%H:%M").time()

                # 이번 달의 해당 날짜 계산
                try:
                    trigger_time = now.replace(
                        day=day,
                        hour=target_time.hour,
                        minute=target_time.minute,
                        second=0,
                        microsecond=0,
                    )
                except ValueError:
                    # 이번 달에 해당 날짜가 없는 경우 (예: 2월 30일), 다음 달로 넘김 (간단한 처리)
                    if now.month == 12:
                        trigger_time = now.replace(
                            year=now.year + 1,
                            month=1,
                            day=1,
                            hour=target_time.hour,
                            minute=target_time.minute,
                            second=0,
                            microsecond=0,
                        )
                    else:
                        trigger_time = now.replace(
                            month=now.month + 1,
                            day=1,
                            hour=target_time.hour,
                            minute=target_time.minute,
                            second=0,
                            microsecond=0,
                        )

                if trigger_time <= now:
                    # 다음 달로 이동
                    if trigger_time.month == 12:
                        trigger_time = trigger_time.replace(
                            year=trigger_time.year + 1, month=1
                        )
                    else:
                        trigger_time = trigger_time.replace(
                            month=trigger_time.month + 1
                        )
                    pass

        except Exception as e:
            await interaction.response.send_message(
                f"❌ 설정값 오류: {e}\n형식을 확인해주세요.", ephemeral=True
            )
            return

        schedule_item = {
            "id": str(uuid.uuid4()),
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
            "trigger_time": trigger_time.isoformat(),
            "message": message,
            "created_at": now.isoformat(),
            "type": "recurring",
            "repeat_type": repeat_type,
            "repeat_value": value,
        }

        self.schedules.append(schedule_item)
        self.save_schedules()

        await interaction.response.send_message(
            f"✅ 반복 예약 완료!\n🔄 주기: {repeat_type} ({value})\n📅 첫 실행: {trigger_time.strftime('%Y-%m-%d %H:%M')}\n💬 메시지: {message}",
            ephemeral=True,
        )

    class DeleteSelect(discord.ui.Select):
        def __init__(self, schedules, cog):
            self.cog = cog
            options = []
            for i, item in enumerate(schedules[:25]):
                dt = datetime.fromisoformat(item["trigger_time"])

                type_str = "일반"
                if item.get("type") == "recurring":
                    rtype = item.get("repeat_type", "?")
                    rval = item.get("repeat_value", "")
                    type_str = f"반복({rtype})"

                label = f"{i+1}. [{type_str}] {dt.strftime('%m-%d %H:%M')}"
                description = (
                    (item["message"][:50] + "..")
                    if len(item["message"]) > 50
                    else item["message"]
                )
                options.append(
                    discord.SelectOption(
                        label=label, description=description, value=item["id"]
                    )
                )

            super().__init__(
                placeholder="삭제할 예약을 선택하세요...",
                min_values=1,
                max_values=1,
                options=options,
            )

        async def callback(self, interaction: discord.Interaction):
            selected_id = self.values[0]
            to_remove = next(
                (item for item in self.cog.schedules if item["id"] == selected_id), None
            )

            if to_remove:
                self.cog.schedules.remove(to_remove)
                self.cog.save_schedules()
                await interaction.response.send_message(
                    "🗑️ 예약이 삭제되었습니다.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ 이미 삭제되었거나 존재하지 않는 예약입니다.", ephemeral=True
                )

    class DeleteView(discord.ui.View):
        def __init__(self, schedules, cog):
            super().__init__()
            self.add_item(SchedulerCog.DeleteSelect(schedules, cog))

    @schedule_group.command(
        name="리스트", description="현재 등록된 예약 목록을 확인하고 관리합니다."
    )
    async def list_reservations(self, interaction: discord.Interaction):
        user_schedules = [
            s
            for s in self.schedules
            if s["guild_id"] == interaction.guild_id
            and s["user_id"] == interaction.user.id
        ]

        user_schedules.sort(key=lambda x: x["trigger_time"])

        if not user_schedules:
            await interaction.response.send_message(
                "📭 등록된 예약 메시지가 없습니다.", ephemeral=True
            )
            return

        embed = discord.Embed(title="📅 예약된 메시지 목록", color=discord.Color.blue())
        description = ""
        for idx, item in enumerate(user_schedules):
            dt = datetime.fromisoformat(item["trigger_time"])
            msg_preview = (
                (item["message"][:20] + "..")
                if len(item["message"]) > 20
                else item["message"]
            )

            type_info = "일반"
            if item.get("type") == "recurring":
                rtype = item.get("repeat_type")
                rval = item.get("repeat_value")
                type_info = f"🔄 {rtype} ({rval})"

            description += f"**{idx+1}.** {dt.strftime('%Y-%m-%d %H:%M')} | {type_info} | {msg_preview}\n"

        embed.description = description
        embed.set_footer(text="아래 메뉴에서 삭제할 예약을 선택할 수 있습니다.")

        view = self.DeleteView(user_schedules, self)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def calculate_next_run(self, item, current_trigger):
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
            print(f"다음 실행 시간 계산 오류: {e}")
            return None
        return None

    @tasks.loop(seconds=30)
    async def check_schedule_task(self):
        now = datetime.now(SEOUL_TZ)
        to_remove = []
        to_update = []

        for item in self.schedules:
            try:
                trigger_time = datetime.fromisoformat(item["trigger_time"])

                if now >= trigger_time:
                    channel = self.bot.get_channel(item["channel_id"])
                    if channel:
                        try:
                            prefix = "⏰ **예약 메시지**"
                            if item.get("type") == "recurring":
                                prefix = "🔄 **반복 메시지**"

                            await channel.send(
                                f"{prefix} (<@{item['user_id']}>):\n{item['message']}"
                            )
                        except Exception as e:
                            print(
                                f"메시지 전송 실패 (channel={item['channel_id']}): {e}"
                            )
                    else:
                        print(f"채널을 찾을 수 없음: {item['channel_id']}")

                    if item.get("type") == "recurring":
                        next_run = self.calculate_next_run(item, trigger_time)
                        if next_run:
                            item["trigger_time"] = next_run.isoformat()
                            to_update.append(item)
                        else:
                            to_remove.append(item)
                    else:
                        to_remove.append(item)
            except Exception as e:
                print(f"스케줄 처리 중 오류: {e}")

        if to_remove or to_update:
            for item in to_remove:
                if item in self.schedules:
                    self.schedules.remove(item)
            self.save_schedules()

    @check_schedule_task.before_loop
    async def before_check_schedule_task(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(SchedulerCog(bot))
