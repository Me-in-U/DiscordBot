# cogs/music.py
import asyncio
import collections
import concurrent.futures
from datetime import datetime
import os
import time
from dataclasses import dataclass, field
from typing import Deque, Optional, Tuple

import discord
import yt_dlp as youtube_dl
from discord import Embed, Message, Object, TextChannel, app_commands
from discord.ext import commands
from discord.ui import Button, View, button
from dotenv import load_dotenv
import re
from discord.utils import utcnow
import subprocess
from discord import AudioSource

load_dotenv()
GUILD_ID = int(os.getenv("GUILD_ID"))  # 손팬노 길드 ID
TEST_GUILD = Object(id=GUILD_ID)
H_BAR = "\u2015"
youtube_dl.utils.bug_reports_message = lambda *args, **kwargs: ""
ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -ac 2 -ar 48000 -acodec libopus -loglevel verbose",
}
debug = False


ytdl = youtube_dl.YoutubeDL(
    {
        "format": "bestaudio/best",
        "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
        "restrictfilenames": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "logtostderr": True,
        "verbose": True,
        "quiet": False,
        "no_warnings": True,
        "default_search": "auto",
        # "listformats": True,
        "source_address": "0.0.0.0",  # bind to ipv4 since ipv6 addresses cause issues sometimes
    }
)


@dataclass
class GuildMusicState:
    player: Optional["YTDLSource"] = None
    start_ts: float = 0.0
    paused_at: Optional[float] = None
    queue: Deque["YTDLSource"] = field(default_factory=collections.deque)
    control_channel: Optional[TextChannel] = None
    control_msg: Optional[Message] = None
    control_view: Optional[View] = None
    updater_task: Optional[asyncio.Task] = None
    is_loop: bool = False
    is_seeking: bool = False
    is_skipping: bool = False


class YTDLSource:
    def __init__(
        self,
        source: discord.FFmpegOpusAudio,
        *,
        data,
    ):
        self.source = source
        self.data = data
        self.title = data.get("title")
        self.webpage_url = data.get("webpage_url")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False, start_time: int = 0):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream)
        )
        if "entries" in data:
            data = data["entries"][0]
        print("[from_url] data['title']:", data.get("title"))
        print("[from_url] data['duration']:", data.get("duration"))
        print(
            "[from_url] data['formats']:",
            [f["format_id"] for f in data.get("formats", [])],
        )
        audio_url = data["url"] if stream else ytdl.prepare_filename(data)

        # ffmpeg 에 -ss(start_time) 옵션 추가
        opts = ffmpeg_options.copy()
        if start_time > 0:
            opts["options"] = f"-ss {start_time} " + opts["options"]
        source = discord.FFmpegOpusAudio(audio_url, **opts)

        return cls(source=source, data=data)


# ! 기본 임베드에 붙을 뷰
class MusicHelperView(View):
    def __init__(self, cog: "MusicCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @button(
        label="🔍 검색", style=discord.ButtonStyle.primary, custom_id="music_search"
    )
    async def search_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(SearchModal(self.cog))


# ! 음악 재생시 붙을 뷰
class MusicControlView(View):
    def __init__(self, cog: "MusicCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @button(
        label="⏸️ 일시정지", style=discord.ButtonStyle.secondary, custom_id="music_pause"
    )
    async def pause_btn(self, interaction: discord.Interaction, button: Button):
        await self.cog._pause(interaction)

    @button(
        label="▶️ 다시재생",
        style=discord.ButtonStyle.secondary,
        custom_id="music_resume",
    )
    async def resume_btn(self, interaction: discord.Interaction, button: Button):
        await self.cog._resume(interaction)

    @button(label="⏭️ 스킵", style=discord.ButtonStyle.primary, custom_id="music_skip")
    async def skip_btn(self, interaction: discord.Interaction, button: Button):
        await self.cog._skip(interaction)

    @button(
        label="🔀 대기열", style=discord.ButtonStyle.secondary, custom_id="music_queue"
    )
    async def queue_btn(self, interaction: discord.Interaction, button: Button):
        await self.cog._show_queue(interaction)

    @button(
        label="⏩ 구간이동", style=discord.ButtonStyle.secondary, custom_id="music_seek"
    )
    async def seek_btn(self, interaction: discord.Interaction, button: Button):
        # 모달을 띄워서 몇 초(or mm:ss) 이동할지 입력받습니다.
        await interaction.response.send_modal(SeekModal(self.cog))

    @button(label="⏹️ 정지", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: Button):
        await self.cog._stop(interaction)

    @button(
        label="🔁 반복", style=discord.ButtonStyle.secondary, custom_id="music_loop"
    )
    async def loop_btn(self, interaction: discord.Interaction, button: Button):
        await self.cog._toggle_loop(interaction)

    @button(
        label="🔍 검색", style=discord.ButtonStyle.primary, custom_id="music_search"
    )
    async def search_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(SearchModal(self.cog))


# ! 구간 탐색 모달
class SeekModal(discord.ui.Modal, title="구간이동"):
    time = discord.ui.TextInput(
        label="가록될 시간 (mm:ss 또는 초)", placeholder="예: 1:23 또는 83"
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        t = self.time.value
        seconds = (
            int(t.split(":")[0]) * 60 + int(t.split(":")[1]) if ":" in t else int(t)
        )
        await self.cog._seek(interaction, seconds)


# ! 음악 검색 버튼 누르면 열릴 모달
class SearchModal(discord.ui.Modal, title="음악검색"):
    query = discord.ui.TextInput(
        label="음악의 제목이나 링크를 입력하세요",
        placeholder="예: Michael Jackson - Bad Lyrics",
    )

    def __init__(self, cog: "MusicCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._play(interaction, self.query.value)


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}  # 길드별 상태 저장

    # !길드의 State 리턴
    def _get_state(self, guild_id: int) -> GuildMusicState:
        return self.states.setdefault(guild_id, GuildMusicState())

    def make_timeline_line(self, elapsed: int, total: int, length: int = 16) -> str:
        def format_time(seconds: int) -> str:
            m, s = divmod(seconds, 60)
            return f"{m:02}:{s:02}"

        """───01:26──03:37 (39%)"""
        elapsed_fmt = format_time(elapsed)
        total_fmt = format_time(total)
        pct = int(elapsed / total * 100) if total else 0
        _, filled = self.make_progress_bar(elapsed, total, length)
        left = H_BAR * filled
        right = H_BAR * (length - filled)
        return f"{left}{elapsed_fmt}{right} {total_fmt} ({pct}%)"

    def make_progress_bar(
        self, elapsed: int, total: int, length: int = 23
    ) -> Tuple[str, int]:
        if total == 0:
            return "▱" * length, 0
        filled = int(length * elapsed / total)
        return "▰" * filled + "▱" * (length - filled), filled

    # ?완
    # !메시지 수정(임베드, 뷰)
    async def _edit_msg(self, state, embed, view):
        try:
            now = utcnow()
            # ! 메시지 1시간 초과 → 새 메시지 전송 + 이전 메시지 삭제
            if (now - state.control_msg.created_at).total_seconds() > 3600:
                new_msg = await state.control_channel.send(embed=embed, view=view)
                try:
                    await state.control_msg.delete()
                except discord.HTTPException as e:
                    print(f"[WARN] 이전 메시지 삭제 실패: {e}")
                state.control_msg = new_msg
                return
            await state.control_msg.edit(embed=embed, view=view)
        except discord.HTTPException as e:
            if getattr(e, "code", None) == 30046:
                new_msg = await state.control_channel.send(embed=embed, view=view)
                try:
                    await state.control_msg.delete()
                except discord.HTTPException as e:
                    print(f"[WARN] 이전 메시지 삭제 실패: {e}")
                state.control_msg = new_msg
            else:
                raise

    # ! 노래 재생 상황 업데이트 루프
    async def _updater_loop(self, guild_id: int):
        state = self._get_state(guild_id)
        try:
            print("[_updater_loop] updater_task 루프 시작")
            while state.player:
                voice_client = state.control_msg.guild.voice_client
                if not voice_client:
                    print("[_updater_loop] voice_client 연결 끊김")
                    return await self._on_song_end(guild_id)
                if voice_client.is_paused():
                    print("[_updater_loop] paused()")
                    await asyncio.sleep(1)
                    continue
                elapsed = int(time.time() - state.start_ts)
                total = state.player.data.get("duration", 0)
                print("[_updater_loop] elapsed:", elapsed, "/ total:", total)

                # !노래시간이 지났고 반복이 아니고 구간이동중이 아니면 종료 호출
                if (
                    total > 0
                    and elapsed >= total
                    and not state.is_loop
                    and not state.is_seeking
                ):
                    print("[_updater_loop] return _on_song_end")
                    return await self._on_song_end(guild_id)

                # ! 메시지 수정(임베드, 뷰)
                embed = self._make_playing_embed(state.player, guild_id, elapsed)
                await self._edit_msg(state, embed, state.control_view)
                await asyncio.sleep(5)
        finally:
            print("[_updater_loop] updater_task 루프 종료")
            state.updater_task = None

    # ?완
    # ! 메시지 자동 삭제
    async def _auto_delete(self, msg: discord.Message, delay: float = 5.0):
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except discord.HTTPException:
            pass

    # ?완
    # ! 기본 임베드
    def _make_default_embed(self) -> Embed:
        try:
            # ! 임베드 기본 설정
            embed = Embed(
                title="🎵 신창섭의 다해줬잖아",
                description="명령어로 음악을 재생·일시정지·스킵할 수 있습니다.\n 재생이후 버튼을 통해 제어도 가능합니다.",
                color=0xFFC0CB,
                timestamp=datetime.now(),
            )
            # ! 도움말 섹션
            embed.add_field(
                name="❓ 사용법",
                value=(
                    "• `/재생 <URL/검색어>`: 유튜브 <URL/검색어>로 즉시 재생\n"
                    "• `/스킵`: 현재 재생중인 곡 스킵(다음 대기열 재생)\n"
                    "• `/일시정지`, 현재 재생중인 곡 일시정지\n"
                    "• `/다시재생`: 일시정지된 곡 다시재생\n"
                    "• `/정지`: 노래 종료 후 신창섭 퇴장\n\n"
                    "👉 재생시 생기는 버튼을 눌러도 동일 기능을 사용할 수 있습니다."
                ),
                inline=False,
            )
            # ! footer
            embed.set_footer(
                text=f"정상화 해줬잖아. 그냥 다 해줬잖아.",
                icon_url=self.bot.user.avatar.url,  # 봇 프로필 아이콘
            )
            return embed
        except Exception as e:
            print("!! make_empty_embed 예외 발생:", e, flush=True)
            import traceback

            traceback.print_exc()
            raise

    # TODO: 음악 신청자 정보 띄우기
    # ! 노래 재생시 임베드
    def _make_playing_embed(
        self, player: YTDLSource, guild_id: int, elapsed: int = 0
    ) -> Embed:
        try:
            total = player.data.get("duration", 0)
            # ! 임베드 기본 설정
            embed = Embed(title="🎵 신창섭의 다해줬잖아", color=0xFFC0CB)
            # ! 섬네일
            embed.set_thumbnail(url=player.data.get("thumbnail"))
            embed.add_field(name="곡 제목", value=player.title, inline=False)
            # ! 진행바 생성
            timeline = self.make_timeline_line(elapsed, total)
            bar, _ = self.make_progress_bar(elapsed, total)
            embed.add_field(name="진행", value=f"{timeline}\n`{bar}`", inline=False)
            # ! footer에 반복 상태
            state = self._get_state(guild_id)
            embed.set_footer(
                text=f"반복: {'켜짐' if state.is_loop else '꺼짐'}",
                icon_url=self.bot.user.avatar.url,
            )  # 봇 프로필 아이콘
            return embed
        except Exception as e:
            print("!! _make_playing_embed 예외 발생:", e, flush=True)
            import traceback

            traceback.print_exc()
            raise

    # ?완
    # ! 전용채널의 봇 댓글 가져오거나 생성
    async def _get_or_create_panel(self, guild: discord.Guild):
        # ! 상태 기본값 설정
        state = self._get_state(guild.id)

        # ! 채널 확보
        control_channel = discord.utils.get(guild.text_channels, name="🎵ㆍ神-음악채널")

        # ! 채널 없으면 생성
        if control_channel is None:
            print("[채널 없음]->", end="")
            # ! 권한 설정
            bot_member = guild.get_member(self.bot.user.id)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(send_messages=True),
                bot_member: discord.PermissionOverwrite(
                    send_messages=True, embed_links=True, read_messages=True
                ),
            }
            control_channel = await guild.create_text_channel(
                "🎵ㆍ神-음악채널", overwrites=overwrites
            )
            print("[채널 생성됨]")

        # ! 상태 업데이트, 기본 임베드 뷰 생성
        print("[길드 상태 업데이트, 기본 임베드 뷰 생성]")
        embed = self._make_default_embed()
        state.control_channel = control_channel
        state.control_view = MusicHelperView(self)

        # ! 과거 메시지 뒤져보기
        history = control_channel.history(limit=50)
        if history:
            async for control_msg in history:
                if control_msg.author == guild.me and control_msg.embeds:
                    em = control_msg.embeds[0]
                    if em.title == "🎵 신창섭의 다해줬잖아":
                        print("[기존 임베드 발견]")
                        # ! 메시지 수정(임베드, 뷰)
                        state.control_msg = control_msg
                        await self._edit_msg(state, embed, state.control_view)
                        return

        # ! 없으면 새로 보내기
        print("[기존 메시지 없음] -> 전송")
        control_msg = await control_channel.send(embed=embed, view=state.control_view)
        state.control_msg = control_msg
        return

    # ?완
    # !노래 재생 or 대기열
    async def _play(self, interaction, url: str):
        # ! 기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client
        # ! 봇이 음성 채널에 없음
        if not voice_client:
            # ! 유저가 음성채널에 없음
            if not (ch := interaction.user.voice and interaction.user.voice.channel):
                return await interaction.followup.send(
                    "❌ 먼저 음성 채널에 들어가 있어야 합니다.", ephemeral=True
                )
            # ! 봇을 채널 연결
            voice_client = await ch.connect()

        # ! url인지 확인 & pre_src에 저장
        player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
        if not re.match(r"^https?://", url):
            print("[_play] url아님:", url)
            print("-> 변환된 url:", getattr(player, "webpage_url", None), flush=True)
        else:
            print("[_play] url:", url)
        print("-> title:", getattr(player, "title", None), flush=True)

        # ! 이미 재생 중이면 큐에 추가
        state = self._get_state(interaction.guild.id)
        if voice_client.is_playing():
            state.queue.append(player)
            # ! 완료 메시지
            msg = await interaction.followup.send(
                f"▶ **대기열에 추가되었습니다.**: {player.title}", ephemeral=True
            )
            asyncio.create_task(self._auto_delete(msg, 5.0))
            return

        # !상태 업데이트
        state.player = player
        state.start_ts = time.time()
        state.paused_at = None

        # ! play & updater 재시작
        self._vc_play(guild_id=guild_id, source=player.source)
        await self._restart_updater(guild_id)

        # ! 임베드 및 진행 업데이터 시작
        embed = self._make_playing_embed(player, guild_id)
        view = MusicControlView(self)
        state.control_view = view
        await self._edit_msg(state=state, embed=embed, view=view)

        # ! 메시지
        msg = await interaction.followup.send(
            f"▶ 재생: **{player.title}**", ephemeral=True
        )
        asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _pause(self, interaction):
        # !기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self.states.setdefault(guild_id, GuildMusicState())
        voice_client = interaction.guild.voice_client
        # !재생중 아님
        if not voice_client or not voice_client.is_playing():
            msg = await interaction.followup.send(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))
        print("[일시정지]")
        voice_client.pause()
        # !상태설정
        state.paused_at = time.time()
        # !메시지
        msg = await interaction.followup.send("⏸️ 일시정지했습니다.", ephemeral=True)
        return asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _resume(self, interaction):
        # !기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        voice_client = interaction.guild.voice_client
        # !재생중 아님
        if not voice_client or not voice_client.is_paused():
            msg = await interaction.followup.send(
                "❌ 일시정지된 음악이 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))
        print("[다시재생]")
        voice_client.resume()
        # !상태설정
        if state.paused_at:
            delta = time.time() - state.paused_at
            state.start_ts += delta
            state.paused_at = None
        # !메시지
        msg = await interaction.followup.send("▶️ 다시 재생합니다.", ephemeral=True)
        return asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _skip(self, interaction: discord.Interaction):
        print("[스킵]")
        # ! 기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            msg = await interaction.followup.send(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))

        if state.is_loop:
            # ! 현재 트랙 강제 중단
            state.is_skipping = True
            voice_client.stop()
            state.is_skipping = False
            msg_text = "🔁 반복 모드: 처음부터 재생합니다."
        else:
            # ! queue나 다음 트랙 로직은 on_song_end에 맡김
            voice_client.stop()
            msg_text = "⏭️ 스킵합니다."

        # !메시지
        msg = await interaction.followup.send(msg_text, ephemeral=True)
        asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _stop(self, interaction: discord.Interaction):
        print("[정지]")
        await interaction.response.defer(thinking=True, ephemeral=True)
        state = self._get_state(interaction.guild.id)
        voice_client = interaction.guild.voice_client
        if not voice_client:
            msg = await interaction.followup.send(
                "❌ 봇이 음성채널에 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))
        await voice_client.disconnect()

        # ! reset panel
        state.control_view = control_view = MusicHelperView(self)
        embed = self._make_default_embed()
        await self._edit_msg(state, embed, state.control_view)

        # ! 재생 상태 완전 초기화
        state.player = None
        if state.updater_task:
            state.updater_task.cancel()
            state.updater_task = None

        # ! 메시지
        msg = await interaction.followup.send("⏹️ 정지하고 나갑니다.", ephemeral=True)
        return asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _show_queue(self, interaction: discord.Interaction):
        print("[대기열보기]")
        await interaction.response.defer(thinking=True, ephemeral=True)
        state = self._get_state(interaction.guild.id)
        if not state.queue:
            msg = await interaction.followup.send(
                "❌ 대기열이 비어있습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))

        n = len(state.queue)
        # !재생 중 정보
        desc_lines = []
        if state.player and state.player.title:
            total = state.player.data.get("duration", 0)
            m, s = divmod(total, 60)
            uploader = state.player.data.get("uploader") or "알 수 없음"
            desc_lines.append(
                f"**재생 중.** \n"
                f"[{state.player.title}]({state.player.webpage_url})"
                f"({m:02}:{s:02}) - {uploader}"
            )
            desc_lines.append("")  # 구분선 역할

        # 대기열 리스트
        # ── 수정 후 _show_queue: None 처리 ──
        for i, player in enumerate(state.queue, start=1):
            desc_lines.append(f"{i}. [{player.title}]({player.webpage_url})")

        embed = Embed(
            title=f"대기열 - {n}개의 곡",
            description="\n".join(desc_lines),
            color=0x99CCFF,
        )

        msg = await interaction.followup.send(embed=embed, ephemeral=True)
        return asyncio.create_task(self._auto_delete(msg, 20.0))

    async def _restart_updater(self, guild_id: int):
        print("[_restart_updater] 호출")
        # ! 기본정보 로드
        state = self._get_state(guild_id)

        # ! task 종료
        if state.updater_task:
            print("[_restart_updater] updater_task 종료")
            state.updater_task.cancel()

        # ! task 종료 대기
        while state.updater_task:
            print("[_restart_updater] updater_task 종료 대기")
            await asyncio.sleep(0.5)

        # ! task 재등록
        print("[_restart_updater] task 재등록")
        state.updater_task = asyncio.create_task(self._updater_loop(guild_id))
        await asyncio.sleep(1)

    async def _seek(self, interaction: discord.Interaction, seconds: int):
        print("[구간이동]")
        # ! 기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        voice_client = interaction.guild.voice_client
        if not voice_client or not state.player:
            # ! 메시지
            msg = await interaction.followup.send(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))

        # ! 새로운 player 생성 (start_time 포함)
        player = await YTDLSource.from_url(
            url=state.player.webpage_url,
            loop=self.bot.loop,
            stream=True,
            start_time=seconds,
        )

        # ! 멈추고 재생 위치부터 새 소스 생성
        state.is_seeking = True
        voice_client.stop()

        # ! play & updater 재시작
        self._vc_play(interaction=interaction, source=player.source)
        await self._restart_updater(guild_id)

        # ! 상태 업데이트
        state.player = player
        state.start_ts = time.time() - seconds
        state.paused_at = None

        # ! 메시지 수정(임베드, 뷰)
        embed = self._make_playing_embed(state.player, guild_id, elapsed=seconds)
        await self._edit_msg(state, embed, state.control_view)

        # ! seek 끝
        state.is_seeking = False

        # ! 메시지
        msg = await interaction.followup.send(
            f"⏩ {seconds}초 지점으로 이동했습니다.", ephemeral=True
        )
        asyncio.create_task(self._auto_delete(msg, 5.0))

    # ?완료
    async def _toggle_loop(self, interaction: discord.Interaction):
        """🔁 반복 모드 토글"""
        await interaction.response.defer(thinking=True, ephemeral=True)
        # ! 상태 업데이트
        state = self._get_state(interaction.guild.id)
        state.is_loop = not state.is_loop
        # ! 메시지
        msg = await interaction.followup.send(
            f"🔁 반복 모드 {'켜짐' if state.is_loop else '꺼짐'}", ephemeral=True
        )
        asyncio.create_task(self._auto_delete(msg, 5.0))

    # ?완료
    def _vc_play(
        self, guild_id: int = None, interaction: discord.Interaction = None, source=None
    ):
        # ! 재생 및 다음 곡 콜백 등록
        def _after_play(error):
            if error:
                print("[_after_play] 에러 발생:", error)
            else:
                print("[_after_play] 정상 종료")
            self.bot.loop.create_task(self._on_song_end(guild_id))

        # ! voice_client 가져오기
        if guild_id:
            guild = self.bot.get_guild(guild_id)
            voice_client = guild.voice_client
        else:
            voice_client = interaction.guild.voice_client

        # ! 재생
        try:
            voice_client.play(source, after=_after_play)
        except discord.errors.ClientException:
            print("[_vc_play] ClientException")
            voice_client.stop()
            voice_client.play(source, after=_after_play)

    async def _on_song_end(self, guild_id: int):
        print("[_on_song_end] called")
        # ! 기본정보 로드
        state = self._get_state(guild_id)

        # ! seek 발생시 종료 로직 무시
        if state.is_seeking:
            print("[_on_song_end] seek 작동")
            return

        # ! task 종료, 상태 업데이트
        if state.updater_task:
            state.updater_task.cancel()
        state.paused_at = None
        state.start_ts = time.time()

        # !루프이거나 루프상태인데 스킵하면 처음부터
        if state.is_skipping or state.is_loop:
            print("[_on_song_end] loop/skip 재생")
            audio_url = state.player.data["url"]
            new_source = discord.FFmpegOpusAudio(audio_url, **ffmpeg_options)
            # ! 상태 업데이트
            state.player.source = new_source
            # ! play & updater 재시작
            self._vc_play(guild_id, source=new_source)
            await self._restart_updater(guild_id)
            return

        # !대기열에 곡이 없으면 패널을 빈(embed 초기) 상태로 리셋
        if not state.queue:
            print("[_on_song_end] 다음곡 없음")
            # ! 메시지 수정(임베드, 뷰)
            embed = self._make_default_embed()
            await self._edit_msg(state, embed, state.control_view)
            return

        # ! 상태 업데이트
        print("[_on_song_end] 다음곡 pop")
        state.player = state.queue.popleft()

        # ! 메시지 수정(임베드, 뷰)
        embed = self._make_playing_embed(state.player, guild_id)
        await self._edit_msg(state, embed, state.control_view)

        # ! play & updater 재시작
        self._vc_play(guild_id, source=state.player.source)
        await self._restart_updater(guild_id)

    @app_commands.command(
        name="음악", description="음악 재생 상태와 컨트롤 버튼을 보여줍니다."
    )
    async def 음악(self, interaction: discord.Interaction):
        print("[음악] 명령 시작")
        # !메시지
        await interaction.response.send_message(
            "음악 컨트롤 패널을 설정 중입니다…", ephemeral=True
        )
        # !길드별 State 초기화
        await self._get_or_create_panel(interaction.guild)
        print(f"[음악] Panel updated in 길드: {interaction.guild}")

    @app_commands.command(name="재생", description="유튜브 URL을 재생합니다.")
    @app_commands.describe(url="재생할 유튜브 URL 혹은 검색어")
    async def 재생(self, interaction: discord.Interaction, url: str):
        await self._play(interaction, url)

    @app_commands.command(name="일시정지", description="음악 일시정지")
    async def 일시정지(self, interaction: discord.Interaction):
        await self._pause(interaction)

    @app_commands.command(name="다시재생", description="일시정지된 음악 재생")
    async def 다시재생(self, interaction: discord.Interaction):
        await self._resume(interaction)

    @app_commands.command(name="정지", description="음악 정지 및 퇴장")
    async def 정지(self, interaction: discord.Interaction):
        await self._stop(interaction)

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> Music Cog : on ready!")
        # ! 모든 길드의 패널 설정
        for guild in self.bot.guilds:
            try:
                print("[on_ready] 길드 음악 상태 로드:", guild)
                await self._get_or_create_panel(guild)
            except Exception as e:
                print(f"[on_ready] 길드 {guild.id} 패널 생성 실패: {e}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, discord.errors.ClientException):
            return
        raise


async def setup(bot: commands.Bot):
    cog = MusicCog(bot)
    await bot.add_cog(cog)
    bot.add_view(MusicHelperView(cog))
    bot.add_view(MusicControlView(cog))
    print("Music Cog : setup 완료!")
