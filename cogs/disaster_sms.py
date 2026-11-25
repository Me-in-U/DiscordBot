from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from hashlib import blake2s
from math import ceil

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from util import disaster_sms
from util.guild.channel_settings import get_channels_by_purpose

logger = logging.getLogger(__name__)
PAGE_SIZE = 100
MAX_ALERT_AGE = timedelta(minutes=15)
RELATED_ALERT_AGE = timedelta(hours=6)


async def fetch_notices(service_key: str) -> list[dict]:
    params = {
        "serviceKey": service_key,
        "returnType": "json",
        "pageNo": 1,
        "numOfRows": PAGE_SIZE,
        "crtDt": (datetime.now(disaster_sms.KST) - MAX_ALERT_AGE).strftime("%Y%m%d"),
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(disaster_sms.API_URL, params=params) as response:
                if response.status != 200:
                    raise RuntimeError(f"재난문자 API HTTP {response.status}")
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        # aiohttp exceptions can include the request URL and service key.
        raise RuntimeError("재난문자 API 응답을 읽지 못했습니다.") from None

    if not isinstance(payload, dict):
        raise RuntimeError("재난문자 API 응답 형식이 올바르지 않습니다.")
    code = str((payload.get("header") or {}).get("resultCode", ""))
    if code not in {"0", "00", "0000", "03"}:
        raise RuntimeError("재난문자 API가 요청을 거부했습니다.")
    rows = payload.get("body")
    if code == "03" or rows is None:
        return []
    if not isinstance(rows, list):
        raise RuntimeError("재난문자 API 본문 형식이 올바르지 않습니다.")
    return rows


class DisasterSmsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service_key = os.getenv("SAFETYDATA_SERVICE_KEY", "").strip()
        self.daily_quota = min(1000, int(os.getenv("SAFETYDATA_DAILY_QUOTA") or "1000"))

    async def cog_load(self) -> None:
        if self.service_key and self.daily_quota > 0:
            self.poll.change_interval(seconds=ceil(90_000 / self.daily_quota))
            self.poll.start()

    async def cog_unload(self) -> None:
        self.poll.cancel()

    @app_commands.command(name="재난문자", description="현재 채널에 전국 주요 재난문자 알림을 설정합니다.")
    @app_commands.rename(status="상태")
    @app_commands.describe(status="true면 현재 채널에 알림을 설정하고 false면 해제합니다.")
    async def configure_disaster_sms(self, interaction: discord.Interaction, status: bool) -> None:
        if (
            interaction.guild_id is None
            or not isinstance(interaction.user, discord.Member)
            or not interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "서버 관리자만 재난문자 알림을 설정할 수 있습니다.", ephemeral=True
            )
            return
        if status and not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "텍스트 채널에서 재난문자 알림을 설정해 주세요.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel_id = interaction.channel_id if status else None
        await disaster_sms.configure_channel(interaction.guild_id, channel_id)
        if channel_id is None:
            message = "재난문자 알림을 해제했습니다."
        else:
            message = f"<#{channel_id}>에 전국 주요 재난문자 알림을 설정했습니다."
            if not self.poll.is_running():
                message += "\nAPI 설정이 준비되면 알림을 시작합니다."
        await interaction.followup.send(message, ephemeral=True)

    @tasks.loop(seconds=90)
    async def poll(self) -> None:
        try:
            if not await get_channels_by_purpose(disaster_sms.CHANNEL_TYPE):
                return
            rows = await fetch_notices(self.service_key)
            now = datetime.now(disaster_sms.KST)
            notices = []
            for row in rows:
                try:
                    timestamp = disaster_sms.notice_time(row)
                    serial = int(row["SN"])
                except (KeyError, TypeError, ValueError):
                    logger.warning("재난문자 API의 시각 또는 일련번호가 올바르지 않습니다.")
                    continue
                if now - MAX_ALERT_AGE <= timestamp <= now:
                    notices.append((serial, timestamp, row))

            # shortcut: the first page covers 100 notices per poll, revisit if production volume exceeds it.
            notices.sort(key=lambda notice: notice[0])
            if len(notices) == PAGE_SIZE:
                logger.warning("최근 재난문자가 한 페이지를 모두 채웠습니다.")
            if not notices:
                return

            async with disaster_sms.CHANNEL_LOCK:
                channels = await get_channels_by_purpose(disaster_sms.CHANNEL_TYPE)
                for guild_id, channel_id in channels.items():
                    try:
                        await self.deliver(guild_id, channel_id, notices, now)
                    except Exception:
                        logger.exception("재난문자 전송 실패: guild=%s channel=%s", guild_id, channel_id)
        except Exception:
            logger.exception("전국 재난문자 조회 실패")

    @poll.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def deliver(self, guild_id: int, channel_id: int, notices: list, now: datetime) -> None:
        state = await disaster_sms.load_state(guild_id, channel_id)
        since = datetime.fromisoformat(state["since"])
        state["alerts"] = {
            key: value for key, value in state["alerts"].items()
            if now - datetime.fromisoformat(value) <= RELATED_ALERT_AGE
        }
        channel = None
        saved_serial = state["serial"]
        for serial, timestamp, row in notices:
            if serial <= state["serial"] or timestamp <= since:
                continue
            category = str(row.get("DST_SE_NM") or "기타")
            region = str(row.get("RCPTN_RGN_NM") or "미상")
            area = f"{category}:{region}"
            action = disaster_sms.classify_notice(row, related=area in state["alerts"])
            if action is not None:
                if channel is None:
                    channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild_id:
                        return
                ping = action == "alert"
                title = "전국 재난문자" if ping else "재난문자 해제 또는 정정"
                embed = discord.Embed(
                    title=f"{title} | {category}",
                    description=str(row["MSG_CN"]).strip(),
                    color=discord.Color.red() if ping else discord.Color.blurple(),
                    url=f"{disaster_sms.SOURCE_URL}?sn={serial}",
                    timestamp=timestamp,
                )
                embed.add_field(name="대상 지역", value=region[:1024], inline=False)
                embed.set_footer(text=f"재난안전데이터공유플랫폼 | {row.get('EMRG_STEP_NM') or '미상'}")
                await channel.send(
                    content="@everyone" if ping else None,
                    embed=embed,
                    nonce=blake2s(f"disaster:{channel_id}:{serial}".encode(), digest_size=12).hexdigest(),
                    allowed_mentions=discord.AllowedMentions(
                        everyone=ping, users=False, roles=False, replied_user=False
                    ),
                )
                if ping:
                    state["alerts"][area] = timestamp.isoformat()
                state["serial"] = serial
                await disaster_sms.save_state(guild_id, state)
                saved_serial = serial
            else:
                state["serial"] = serial

        if state["serial"] > saved_serial:
            await disaster_sms.save_state(guild_id, state)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DisasterSmsCommands(bot))
