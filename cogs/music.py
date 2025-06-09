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
import re, aiohttp

load_dotenv()
GUILD_ID = int(os.getenv("GUILD_ID"))  # 손팬노 길드 ID
TEST_GUILD = Object(id=GUILD_ID)
H_BAR = "\u2015"
youtube_dl.utils.bug_reports_message = lambda *args, **kwargs: ""

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
ytdl = youtube_dl.YoutubeDL(
    {
        "format": "bestaudio/best",
        "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
        "restrictfilenames": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "quiet": True,
        "no_warnings": True,
        "default_search": "auto",
        "source_address": "0.0.0.0",  # bind to ipv4 since ipv6 addresses cause issues sometimes
    }
)


def format_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02}:{s:02}"


def make_progress_bar(elapsed: int, total: int, length: int = 23) -> Tuple[str, int]:
    if total == 0:
        return "▱" * length, 0
    filled = int(length * elapsed / total)
    return "▰" * filled + "▱" * (length - filled), filled


def make_timeline_line(elapsed: int, total: int, length: int = 16) -> str:
    """───01:26──03:37 (39%)"""
    elapsed_fmt = format_time(elapsed)
    total_fmt = format_time(total)
    pct = int(elapsed / total * 100) if total else 0
    _, filled = make_progress_bar(elapsed, total, length)
    left = H_BAR * filled
    right = H_BAR * (length - filled)
    return f"{left}{elapsed_fmt}{right} {total_fmt} ({pct}%)"


@dataclass
class GuildMusicState:
    player: Optional[discord.PCMVolumeTransformer] = None
    start_ts: float = 0.0
    paused_at: Optional[float] = None
    queue: Deque[Tuple[str, str, str]] = field(default_factory=collections.deque)
    control_channel: Optional[TextChannel] = None
    control_msg: Optional[Message] = None
    control_view: Optional[View] = None
    updater_task: Optional[asyncio.Task] = None
    loop: bool = False
    seeking: bool = False


class YTDLSource:
    def __init__(self, opus_source: discord.FFmpegOpusAudio, *, data):
        # PCMVolumeTransformer 제거, FFmpegOpusAudio를 직접 사용
        self.source = opus_source
        self.data = data
        self.title = data.get("title")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False, start_time: int = 0):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream)
        )
        if "entries" in data:
            data = data["entries"][0]
        filename = data["url"] if stream else ytdl.prepare_filename(data)
        # ffmpeg 에 -ss(start_time) 옵션 추가
        opts = ffmpeg_options.copy()
        if start_time > 0:
            opts["before_options"] = f"-ss {start_time} " + opts["before_options"]
        # FFmpeg에게 Opus 인코딩 전담
        opus = discord.FFmpegOpusAudio(filename, **opts)
        return cls(opus_source=opus, data=data)


class MusicHelperView(View):
    def __init__(self, cog: "MusicCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @button(
        label="🔍 검색", style=discord.ButtonStyle.primary, custom_id="music_search"
    )
    async def search_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(SearchModal(self.cog))


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
        self.states: dict[int, GuildMusicState] = {}

    def _get_state(self, guild_id: int) -> GuildMusicState:
        return self.states.setdefault(guild_id, GuildMusicState())

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> Music Cog : on ready!")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        # swallow Discord voice errors
        if isinstance(error, discord.errors.ClientException):
            return
        raise

    async def _auto_delete(self, msg: discord.Message, delay: float = 5.0):
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except discord.HTTPException:
            pass

    async def _enqueue(
        self,
        url: str,
        requester: str,
        interaction: discord.Interaction,
    ):
        print("[큐 추가 url]: ", url)
        state = self._get_state(interaction.guild.id)
        # 1) placeholder 로 바로 추가
        state.queue.append((None, url, requester))

        # 3) 백그라운드로 제목만 채우기
        asyncio.create_task(self._fill_title(interaction.guild.id, url, requester))

    async def _fill_title(self, guild_id: int, url: str, requester: str):
        async def fetch_title(url: str) -> str:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as res:
                    html = await res.text()
            m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if m:
                return m.group(1)
            m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else "제목 없음"

        title = await fetch_title(url)
        print("[_fill_title]: ", url, title)
        state = self._get_state(guild_id)
        # 큐에서 placeholder 찾아 교체
        for idx, (old_title, u, r) in enumerate(state.queue):
            if old_title is None and u == url and r == requester:
                state.queue[idx] = (title, u, r)
                break

    def make_empty_embed(self, loop: bool = False) -> Embed:
        try:
            embed = Embed(
                title="🎵 신창섭의 다해줬잖아",
                description="명령어로 음악을 재생·일시정지·스킵할 수 있습니다.\n 재생이후 버튼을 통해 제어도 가능합니다.",
                color=0xFFC0CB,
                timestamp=datetime.utcnow(),
            )
            # 도움말 섹션
            embed.add_field(
                name="❓ 사용법",
                value=(
                    "• `/재생 <URL>`: 유튜브 URL로 즉시 재생\n"
                    "• `/스킵`: 현재 재생중인 곡 스킵(다음 대기열 재생)\n"
                    "• `/일시정지`, 현재 재생중인 곡 일시정지\n"
                    "• `/다시재생`: 일시정지된 곡 다시재생\n"
                    "• `/정지`: 노래 종료 후 신창섭 퇴장\n\n"
                    "👉 재생시 생기는 버튼을 눌러도 동일 기능을 사용할 수 있습니다."
                ),
                inline=False,
            )
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

    def _make_playing_embed(self, player: YTDLSource, guild_id: int) -> Embed:
        try:
            total = player.data.get("duration", 0)
            embed = Embed(title="🎵 신창섭의 다해줬잖아", color=0xFFC0CB)
            embed.set_thumbnail(url=player.data.get("thumbnail"))
            embed.add_field(name="곡 제목", value=player.title, inline=False)
            # 초기값
            timeline = make_timeline_line(0, total)
            bar, _ = make_progress_bar(0, total)
            embed.add_field(name="진행", value=f"{timeline}\n`{bar}`", inline=False)
            # footer에 반복 상태
            state = self._get_state(guild_id)
            embed.set_footer(text=f"반복: {'켜짐' if state.loop else '꺼짐'}")
            return embed
        except Exception as e:
            print("!! _make_playing_embed 예외 발생:", e, flush=True)
            import traceback

            traceback.print_exc()
            raise

    @staticmethod
    def update_progress(embed: Embed, elapsed: int, total: int):
        timeline = make_timeline_line(elapsed, total)
        bar, _ = make_progress_bar(elapsed, total)
        embed.set_field_at(1, name="진행", value=f"{timeline}\n`{bar}`")

    async def _get_or_create_panel(self, guild: discord.Guild):
        state = self._get_state(guild.id)
        if state.control_msg:
            self.bot.add_view(state.control_view)
            return state.control_channel, state.control_msg, state.control_view

        # 1) 채널 확보
        music_ch = discord.utils.get(guild.text_channels, name="🎵ㆍ神-음악채널")
        if music_ch is None:
            print("[채널 없음]")
            # bot.user 를 명시적으로 가져와서 권한 오버라이드
            bot_member = guild.get_member(self.bot.user.id)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(send_messages=False),
                bot_member: discord.PermissionOverwrite(
                    send_messages=True, embed_links=True, read_messages=True
                ),
            }
            print("[채널 생성됨]")
            music_ch = await guild.create_text_channel(
                "🎵ㆍ神-음악채널", overwrites=overwrites
            )

        # 2) 과거 메시지 뒤져보기
        async for msg in music_ch.history(limit=50):
            if msg.author == guild.me and msg.embeds:
                em = msg.embeds[0]
                if em.title == "🎵 신창섭의 다해줬잖아":
                    is_playing = len(em.fields) > 1 and em.fields[0].name == "곡 제목"
                    view = (
                        MusicControlView(self) if is_playing else MusicHelperView(self)
                    )
                    state.control_channel = music_ch
                    state.control_msg = msg
                    state.control_view = view
                    self.bot.add_view(view)
                    print("[기존 뷰 발견]")
                    return music_ch, msg, view

        # 3) 없으면 새로 보내기
        print("[기존 뷰 없음]")
        view = MusicHelperView(self)
        embed = self.make_empty_embed(loop=state.loop)
        self.bot.add_view(view)
        msg = await music_ch.send(embed=embed, view=view)
        state.control_channel = music_ch
        state.control_msg = msg
        state.control_view = view
        return music_ch, msg, view

    async def _play_song(
        self,
        guild_id: int,
        url: str,
        pre_player: YTDLSource = None,
        start_time: int = 0,
    ):
        print("[재생]")
        state = self._get_state(guild_id)
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client
        if not vc:
            return

        # YTDLSource 생성
        if pre_player:
            player = pre_player
        else:
            player = await YTDLSource.from_url(
                url, loop=self.bot.loop, stream=True, start_time=start_time
            )
        player.guild = guild

        # 재생 및 다음 곡 콜백 등록
        def _after_play(error):
            # 오류 무시하고, _on_song_end를 태스크로 실행
            self.bot.loop.create_task(self._on_song_end(guild_id))

        vc.play(player.source, after=_after_play)

        # 상태 업데이트
        state.player = player
        state.start_ts = time.time() - start_time
        state.paused_at = None

        # 임베드 및 진행 업데이터 시작
        embed = self._make_playing_embed(player, guild_id)
        view = MusicControlView(self)
        state.control_view = view
        self.bot.add_view(view)
        print(
            f"[_play_song] 임베드 수정 -> {guild_id}: title={player.title}, total_duration={player.data.get('duration')}"
        )
        try:
            await state.control_msg.edit(embed=embed, view=view)
        except Exception as e:
            print(
                f"[_play_song][ERROR] failed to edit embed for guild {guild_id}: {e}",
                flush=True,
            )
            import traceback

            traceback.print_exc()
        self._restart_updater(guild_id)

    async def _play(self, interaction, url):
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        vc = interaction.guild.voice_client

        # 1) defer + 패널 생성/확보
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self._get_or_create_panel(interaction.guild)

        # 2) 음성 채널에 연결
        if not vc:
            if not (ch := interaction.user.voice and interaction.user.voice.channel):
                return await interaction.followup.send(
                    "❌ 먼저 음성 채널에 들어가 있어야 합니다.", ephemeral=True
                )
            vc = await ch.connect()

        # url인지 확인 & pre_src에 저장
        if not re.match(r"^https?://", url):
            print("[url아님]: ", url)
            pre_src = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            url = pre_src.data["webpage_url"]
            print("[변환된 url]: ", url)
        else:
            pre_src = None

        # 3) 이미 재생 중이면, 메타데이터만 추출해서 큐에 추가
        if vc.is_playing():
            asyncio.create_task(self._enqueue(url, interaction.user.name, interaction))
            msg = await interaction.followup.send(
                f"▶ **대기열에 추가되었습니다.**", ephemeral=True
            )
            asyncio.create_task(self._auto_delete(msg, 5.0))
            return

        # 4) 통합 재생 로직 사용 (_play_song 호출 → 임베드 갱신 & updater_loop 자동 시작)
        await self._play_song(guild_id, url, pre_src)
        # 5) 사용자에게 완료 메시지
        current = self._get_state(guild_id).player
        msg = await interaction.followup.send(
            f"▶ 재생: **{current.title}**", ephemeral=True
        )
        asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _pause(self, interaction):
        print("[일시정지]")
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self.states.setdefault(guild_id, GuildMusicState())
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            msg = await interaction.followup.send(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))
        vc.pause()
        state.paused_at = time.time()
        msg = await interaction.followup.send("⏸️ 일시정지했습니다.", ephemeral=True)
        return asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _resume(self, interaction):
        print("[다시재생]")
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
        vc = interaction.guild.voice_client
        if not vc or not vc.is_paused():
            msg = await interaction.followup.send(
                "❌ 일시정지된 음악이 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))

        vc.resume()
        # 일시정지 보정
        if state.paused_at:
            delta = time.time() - state.paused_at
            state.start_ts += delta
            state.paused_at = None
        msg = await interaction.followup.send("▶️ 다시 재생합니다.", ephemeral=True)
        return asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _skip(self, interaction: discord.Interaction):
        print("[스킵]")
        await interaction.response.defer(thinking=True, ephemeral=True)
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            msg = await interaction.followup.send(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))

        # 바로 현재 트랙 중단 → _on_song_end 로직으로 다음 트랙 재생
        vc.stop()

        msg = await interaction.followup.send("⏭️ 스킵합니다.", ephemeral=True)
        asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _stop(self, interaction: discord.Interaction):
        print("[정지]")
        await interaction.response.defer(thinking=True, ephemeral=True)
        state = self._get_state(interaction.guild.id)
        vc = interaction.guild.voice_client
        if not vc:
            msg = await interaction.followup.send(
                "❌ 봇이 음성채널에 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))
        await vc.disconnect()

        # reset panel
        helper = MusicHelperView(self)
        state.control_view = helper
        self.bot.add_view(helper)
        await state.control_msg.edit(
            embed=self.make_empty_embed(loop=state.loop), view=helper
        )

        # 재생 상태 완전 초기화
        state.player = None
        if state.updater_task:
            state.updater_task.cancel()
            state.updater_task = None

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
        # 재생 중 정보
        desc_lines = []
        if state.player and state.player.title:
            total = state.player.data.get("duration", 0)
            m, s = divmod(total, 60)
            uploader = state.player.data.get("uploader") or "알 수 없음"
            desc_lines.append(
                f"**재생 중.** \n"
                f"[{state.player.title}]({state.player.data['webpage_url']})"
                f"({m:02}:{s:02}) - {uploader}"
            )
            desc_lines.append("")  # 구분선 역할

        # 대기열 리스트
        # ── 수정 후 _show_queue: None 처리 ──
        for i, (title, url, requester) in enumerate(state.queue, start=1):
            display = title or "제목 로딩 중…"
            desc_lines.append(f"{i}. [{display}]({url}) - @{requester}")

        embed = Embed(
            title=f"대기열 - {n}개의 곡",
            description="\n".join(desc_lines),
            color=0x99CCFF,
        )

        msg = await interaction.followup.send(embed=embed, ephemeral=True)
        return asyncio.create_task(self._auto_delete(msg, 20.0))

    def _restart_updater(self, guild_id: int):
        state = self._get_state(guild_id)
        if state.updater_task:
            state.updater_task.cancel()
        state.updater_task = asyncio.create_task(self._updater_loop(guild_id))

    async def _refresh_panel(self, guild_id: int, elapsed: int):
        state = self._get_state(guild_id)
        embed = self._make_playing_embed(state.player, guild_id)
        self.update_progress(embed, elapsed, state.player.data.get("duration", 0))
        try:
            await state.control_msg.edit(embed=embed, view=state.control_view)
        except discord.HTTPException as e:
            if getattr(e, "code", None) == 30046:
                new_msg = await state.control_channel.send(
                    embed=embed, view=state.control_view
                )
                state.control_msg = new_msg
            else:
                raise

    async def _seek(self, interaction: discord.Interaction, seconds: int):
        await interaction.response.defer(thinking=True, ephemeral=True)
        gid = interaction.guild.id
        state = self._get_state(gid)
        vc = interaction.guild.voice_client
        if not vc or not state.player:
            msg = await interaction.followup.send(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
            return asyncio.create_task(self._auto_delete(msg, 5.0))

        # 멈추고 재생 위치부터 새 소스 생성
        state.seeking = True
        vc.stop()

        stream_url = state.player.data["url"]

        # 새로운 FFmpegOpusAudio 생성 (-ss 포함)
        new_source = discord.FFmpegOpusAudio(
            stream_url,
            before_options=f"-ss {seconds} {ffmpeg_options['before_options']}",
            options=ffmpeg_options["options"],
        )
        vc.play(
            new_source,
            after=lambda e: self.bot.loop.create_task(self._on_song_end(gid)),
        )

        # 상태 갱신
        state.player = YTDLSource(new_source, data=state.player.data)
        state.start_ts = time.time() - seconds
        state.paused_at = None

        # seek 끝
        state.seeking = False

        # 진행 바만 갱신 (뷰는 그대로 유지)
        self._restart_updater(gid)
        await self._refresh_panel(gid, seconds)

        # (8) 완료 메시지
        msg = await interaction.followup.send(
            f"⏩ {seconds}초 지점으로 이동했습니다.", ephemeral=True
        )
        asyncio.create_task(self._auto_delete(msg, 5.0))

    # 길드별 진행도 업데이트 코루틴
    async def _updater_loop(self, guild_id: int):
        state = self._get_state(guild_id)
        try:
            while state.player:
                vc = state.control_msg.guild.voice_client
                if not vc or vc.is_paused():
                    await asyncio.sleep(1)
                    continue

                elapsed = int(time.time() - state.start_ts)
                total = state.player.data.get("duration", 0)
                if elapsed >= total:
                    return await self._on_song_end(guild_id)

                await self._refresh_panel(guild_id, elapsed)
                await asyncio.sleep(5)

        finally:
            state.updater_task = None

    async def _toggle_loop(self, interaction: discord.Interaction):
        """🔁 반복 모드 토글"""
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self._get_or_create_panel(interaction.guild)

        state = self._get_state(interaction.guild.id)
        state.loop = not state.loop

        # 재생중 아니면 빈 임베드로 바로 갱신
        # 재생중이면 loop에서 자동 갱신
        if not state.player:
            new_embed = self.make_empty_embed(loop=state.loop)
            await state.control_msg.edit(embed=new_embed, view=state.control_view)
        msg = await interaction.followup.send(
            f"🔁 반복 모드 {'켜짐' if state.loop else '꺼짐'}", ephemeral=True
        )
        asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _on_song_end(self, guild_id: int):
        state = self._get_state(guild_id)
        # seek 중에 vc.stop() → after 콜백이 오면 무시
        if state.seeking:
            state.seeking = False
            return

        # 진행도 업데이트 태스크 취소
        if state.updater_task:
            state.updater_task.cancel()
            state.updater_task = None

        # 반복 모드
        if state.loop:
            url = state.player.data["webpage_url"]
            await self._play_song(guild_id, url)
            return

        # 대기열에 곡이 없으면 패널을 빈(embed 초기) 상태로 리셋
        if not state.queue:
            embed = self.make_empty_embed(loop=state.loop)
            await state.control_msg.edit(embed=embed, view=state.control_view)
            return

        _, url, _ = state.queue.popleft()
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client
        if not vc:
            return

        # 다음 곡 로드 및 재생
        player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)

        def _after_next(error):
            self.bot.loop.create_task(self._on_song_end(guild_id))

        # AudioSource 가 아닐 경우를 대비해 항상 .source 를 넘겨 줍니다.
        try:
            vc.play(player.source, after=_after_next)
        except discord.errors.ClientException:
            vc.stop()
            vc.play(player.source, after=_after_next)

        # 상태 업데이트
        state.player = player
        state.start_ts = time.time()
        state.paused_at = None

        # 컨트롤 패널 임베드 갱신
        embed = self._make_playing_embed(player, guild_id)
        # 컨트롤 패널 임베드 갱신 (오래된 메시지 편집 제한 대응)
        try:
            await state.control_msg.edit(embed=embed, view=state.control_view)
        except discord.errors.HTTPException as e:
            # 30046: 메시지 1시간 이상된 후 편집 제한
            if e.code == 30046:
                # 새 패널 메시지 생성
                ch = state.control_channel
                msg = await ch.send(embed=embed, view=state.control_view)
                state.control_msg = msg
            else:
                raise

        # 새 진행도 업데이트 루프 시작
        state.updater_task = asyncio.create_task(self._updater_loop(guild_id))

    # — UI 버튼을 띄우는 슬래시 커맨드 —
    @app_commands.command(
        name="음악", description="음악 재생 상태와 컨트롤 버튼을 보여줍니다."
    )
    @app_commands.guilds(TEST_GUILD)
    async def 음악(self, interaction: discord.Interaction):
        print("[음악] 명령 시작")
        # 1) 즉시 확인 메시지(또는 defer)로 interaction 응답
        await interaction.response.send_message(
            "음악 컨트롤 패널을 설정 중입니다…", ephemeral=True
        )

        # 2) 패널(채널·메시지·뷰) 확보 or 생성
        music_ch, panel_msg, panel_view = await self._get_or_create_panel(
            interaction.guild
        )

        if panel_msg.embeds[0].fields and len(panel_msg.embeds[0].fields) == 2:
            # make_empty_embed() 로 보낸 상태이니, 진행 필드만 교체
            new_embed = Embed(title="🎵 신창섭의 다해줬잖아", color=0xFFC0CB)
            new_embed.add_field("현재 재생 중", "없음", inline=False)
            new_embed.add_field("진행", "00:00 / 00:00", inline=False)
            await panel_msg.edit(embed=new_embed, view=panel_view)

        print(f"[음악] Panel updated in {music_ch.name}#{panel_msg.id}")

    @app_commands.command(name="재생", description="유튜브 URL을 재생합니다.")
    @app_commands.describe(url="재생할 유튜브 URL 혹은 검색어")
    @app_commands.guilds(TEST_GUILD)
    async def 재생(self, interaction: discord.Interaction, url: str):
        await self._play(interaction, url)

    @app_commands.command(name="일시정지", description="음악 일시정지")
    @app_commands.guilds(TEST_GUILD)
    async def 일시정지(self, interaction: discord.Interaction):
        await self._pause(interaction)

    @app_commands.command(name="다시재생", description="일시정지된 음악 재생")
    @app_commands.guilds(TEST_GUILD)
    async def 다시재생(self, interaction: discord.Interaction):
        await self._resume(interaction)

    @app_commands.command(name="정지", description="음악 정지 및 퇴장")
    @app_commands.guilds(TEST_GUILD)
    async def 정지(self, interaction: discord.Interaction):
        await self._stop(interaction)


async def setup(bot: commands.Bot):
    cog = MusicCog(bot)
    await bot.add_cog(cog)
    bot.add_view(MusicHelperView(cog))
    bot.add_view(MusicControlView(cog))
    print("Music Cog : setup 완료!")
