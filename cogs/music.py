# cogs/music.py
import asyncio
import collections
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Optional, Tuple

import aiohttp
import discord
import yt_dlp as youtube_dl
from discord import Embed, Message, Object, SelectOption, TextChannel, app_commands
from discord.ext import commands
from discord.ui import Button, Select, View, button
from discord.utils import utcnow
from dotenv import load_dotenv

load_dotenv()
GUILD_ID = int(os.getenv("GUILD_ID"))  # 손팬노 길드 ID
TEST_GUILD = Object(id=GUILD_ID)
H_BAR = "\u2015"

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-threads 2 -vn -ac 2 -ar 48000 -acodec libopus -loglevel verbose",
}

search_ytdl = youtube_dl.YoutubeDL(
    {
        "default_search": "auto",
        "extract_flat": True,
        "noplaylist": True,
        "quiet": True,
    }
)

ytdl = youtube_dl.YoutubeDL(
    {
        "format": "bestaudio/best",
        "noplaylist": True,
        "skip_download": True,
        "simulate": True,
        "quiet": True,
        "verbose": False,
        "no_warnings": True,
        "logtostderr": False,
        "ignoreerrors": True,
        "nocheckcertificate": True,
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,
    }
)


async def fetch_stream_url(page_url: str) -> str:
    # ① YouTube 페이지 HTML 한 번만 가져오기
    async with aiohttp.ClientSession() as session:
        async with session.get(page_url) as resp:
            text = await resp.text()

    # ② ytInitialPlayerResponse JSON 추출
    m = re.search(r"ytInitialPlayerResponse\s*=\s*(\{.+?\});", text)
    data = json.loads(m.group(1))

    # ③ adaptiveFormats 중 audio MIME만 필터
    af = data["streamingData"]["adaptiveFormats"]
    audio_formats = [f for f in af if f.get("mimeType", "").startswith("audio/")]

    # ④ 비트레이트 최고 스트림 URL 선택
    best = max(audio_formats, key=lambda f: f.get("averageBitrate", 0))
    return best["url"]


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
        self, source: discord.FFmpegOpusAudio, *, data, requester: discord.User = None
    ):
        self.source = source
        self.data = data
        self.title = data.get("title")
        self.webpage_url = data.get("webpage_url")
        self.requester = requester

    @classmethod
    async def from_url(
        cls, url, *, loop=None, start_time: int = 0, requester: discord.User = None
    ):
        loop = loop or asyncio.get_event_loop()

        # ! 검색어면 먼저 ID만 빠르게 가져오기(제거해도 됨)
        if not re.match(r"^https?://", url):
            search = f"ytsearch5:{url}"
            info = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(search, download=False)
            )
            entry = info["entries"][0]
            url = entry["url"]  # 비디오 ID

        # ! 실제 메타·스트림 준비
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=False, process=False)
        )
        # ! 단일 비디오인 경우
        if "entries" in data:
            data = data["entries"][0]

        # ! 포맷 리스트 중 bestaudio 뽑기
        formats = data.get("formats", [])
        best = max(formats, key=lambda f: f.get("abr", 0) or 0)

        # ! ffmpeg 에 -ss(start_time) 옵션 추가
        audio_url = best["url"]
        opts = ffmpeg_options.copy()
        if start_time > 0:
            opts["options"] = f"-ss {start_time} " + opts["options"]
        source = discord.FFmpegOpusAudio(
            audio_url, **opts, executable="bin\\ffmpeg.exe"
        )

        return cls(source=source, data=data, requester=requester)


# 검색 결과 뷰
class SearchResultView(View):
    def __init__(self, cog, videos: list[dict]):
        # ephemeral select menus only live for 60s
        super().__init__(timeout=None)
        self.cog = cog

        # build up to 10 options
        options: list[SelectOption] = []
        for i, v in enumerate(videos[:10], start=1):
            title = v.get("title", "<제목 없음>")[:60]
            uploader = v.get("uploader") or "알 수 없음"
            dur = int(v.get("duration", 0) or 0)
            m, s = divmod(dur, 60)
            length = f"{m}:{s:02d}"
            label = f"{i}. {title} – {uploader} | 길이: {length}"
            label = label[:100]
            # value must be the video URL, so we can hand it back to _play
            options.append(SelectOption(label=label, value=v["url"]))
        print("[SearchResultView] options:", options)

        # 드롭다운 메뉴 추가(에러 방지를 위해 try/except)
        if options:
            try:
                sel = Select(
                    placeholder="▶️ 재생할 곡을 선택하세요",
                    custom_id="search_select",
                    options=options,
                )
                # callback 연결
                sel.callback = self.on_select
                self.add_item(sel)
            except Exception as e:
                print(f"[WARN] SearchResultView.add_item 실패: {e}")
                # 실패 시 fallback: disabled 버튼으로 안내
                self.clear_items()
                self.add_item(
                    Button(
                        label="❌ 선택지를 생성할 수 없습니다",
                        style=discord.ButtonStyle.secondary,
                        disabled=True,
                    )
                )
        else:
            # 결과가 하나도 없으면 disabled 버튼
            self.add_item(
                Button(
                    label="❌ 검색 결과가 없습니다",
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                )
            )

    async def on_select(self, interaction: discord.Interaction):
        url = interaction.data["values"][0]
        print("[Select 클릭]", url)
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self.cog._play(interaction, url, skip_defer=True)


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
    def __init__(self, cog: "MusicCog", state: "GuildMusicState"):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state

        # ▶️ 다시재생 또는 ⏸️ 일시정지 버튼
        if state.paused_at:
            self.resume_btn = Button(
                label="▶️ 다시재생",
                style=discord.ButtonStyle.primary,
                custom_id="music_resume",
                row=0,
            )
            self.resume_btn.callback = self._on_resume
            self.add_item(self.resume_btn)
        else:
            self.pause_btn = Button(
                label="⏸️ 일시정지",
                style=discord.ButtonStyle.primary,
                custom_id="music_pause",
                row=0,
            )
            self.pause_btn.callback = self._on_pause
            self.add_item(self.pause_btn)

        # 나머지 버튼들
        self.add_control_buttons()

    def add_control_buttons(self):
        skip_btn = Button(
            label="⏭️ 스킵",
            style=discord.ButtonStyle.success,
            custom_id="music_skip",
            row=0,
        )
        stop_btn = Button(
            label="⏹️ 정지",
            style=discord.ButtonStyle.danger,
            custom_id="music_stop",
            row=0,
        )
        queue_btn = Button(
            label="🔀 대기열",
            style=discord.ButtonStyle.secondary,
            custom_id="music_queue",
            row=1,
        )
        seek_btn = Button(
            label="⏩ 구간이동",
            style=discord.ButtonStyle.secondary,
            custom_id="music_seek",
            row=1,
        )
        loop_btn = Button(
            label="🔁 반복",
            style=discord.ButtonStyle.secondary,
            custom_id="music_loop",
            row=1,
        )
        search_btn = Button(
            label="🔍 검색",
            style=discord.ButtonStyle.primary,
            custom_id="music_search_2",
            row=2,
        )

        skip_btn.callback = self._on_skip
        stop_btn.callback = self._on_stop
        queue_btn.callback = self._on_queue
        seek_btn.callback = self._on_seek
        loop_btn.callback = self._on_loop
        search_btn.callback = self._on_search

        for b in [skip_btn, stop_btn, queue_btn, seek_btn, loop_btn, search_btn]:
            self.add_item(b)

    # === 콜백 함수들 ===
    async def _on_pause(self, interaction: discord.Interaction):
        await self.cog._pause(interaction)

    async def _on_resume(self, interaction: discord.Interaction):
        await self.cog._resume(interaction)

    async def _on_skip(self, interaction: discord.Interaction):
        await self.cog._skip(interaction)

    async def _on_stop(self, interaction: discord.Interaction):
        await self.cog._stop(interaction)

    async def _on_queue(self, interaction: discord.Interaction):
        await self.cog._show_queue(interaction)

    async def _on_seek(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self.cog.SeekModal(self.cog))

    async def _on_loop(self, interaction: discord.Interaction):
        await self.cog._toggle_loop(interaction)

    async def _on_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self.cog.SearchModal(self.cog))


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
        # ! 메시지 수정. 실패시 -> 채널 전체 클리어 + 새로 전송
        try:
            now = utcnow()
            if (now - state.control_msg.created_at).total_seconds() > 3600:
                new_msg = await state.control_channel.send(embed=embed, view=view)
                try:
                    await state.control_msg.delete()
                except discord.HTTPException as e:
                    print(f"[WARN] 이전 메시지 삭제 실패: {e}\n-> 채널 전체 클리어 중")
                    await state.control_channel.purge(limit=None)
                state.control_msg = new_msg
                return
            await state.control_msg.edit(embed=embed, view=view)
        except discord.HTTPException as e:
            if getattr(e, "code", None) in (30046, 10008):
                print(f"[WARN] 이전 메시지 삭제 실패: {e}\n-> 채널 전체 클리어 중")
                await state.control_channel.purge(limit=None)
                new_msg = await state.control_channel.send(embed=embed, view=view)
                state.control_msg = new_msg
            else:
                raise

    # ?완
    # ! 노래 재생 상황 업데이트 루프
    async def _updater_loop(self, guild_id: int):
        state = self._get_state(guild_id)
        try:
            print("[_updater_loop] updater_task 루프 시작")
            while state.player:
                voice_client = state.control_msg.guild.voice_client
                # ! voice_client 연결 끊김
                if not voice_client:
                    print("[_updater_loop] voice_client 연결 끊김")
                    await self._stop()
                    return await self._on_song_end(guild_id)
                # ! 봇만 남아있음 → 종료 호출
                if voice_client and len(voice_client.channel.members) == 1:
                    print("[_updater_loop] 봇만 남아있음 → 종료 호출")
                    await self._stop()
                    return await self._on_song_end(guild_id)
                # ! 일시정지 대기
                if voice_client.is_paused():
                    print("[_updater_loop] 일시정지 대기")
                    await asyncio.sleep(1)
                    continue
                # ! 재생시간 계산
                elapsed = int(time.time() - state.start_ts)
                total = state.player.data.get("duration", 0)
                print("[_updater_loop] elapsed:", elapsed, "/ total:", total)
                # ! 노래시간이 지났고 반복이 아니고 구간이동중이 아니면 종료 호출
                if (
                    total > 0
                    and elapsed >= total
                    and not state.is_loop
                    and not state.is_seeking
                ):
                    print(
                        "[_updater_loop] 노래시간이 지났고 반복이 아니고 구간이동중이 아니면 종료 호출"
                    )
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
            requester = player.requester
            requester_name = requester.display_name if requester else "알 수 없음"
            requester_icon = (
                requester.display_avatar.url if requester else self.bot.user.avatar.url
            )

            embed.set_footer(
                text=f"신청자: {requester_name} | 반복: {'켜짐' if state.is_loop else '꺼짐'} | {'⏸️ 일시정지 상태' if state.paused_at else '▶️ 재생중...'}",
                icon_url=requester_icon,
            )
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
                "🎵ㆍ神-음악채널",
                overwrites=overwrites,
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
    async def _play(self, interaction, url: str, skip_defer: bool = False):
        # ? 검색어 처리
        if not re.match(r"^https?://", url):
            # ytsearch로 상위 10개까지 뽑되
            info = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: search_ytdl.extract_info(f"ytsearch10:{url}", download=False),
            )
            raw = info.get("entries", []) or []
            # 유효한 영상 URL만 필터
            videos = [
                e
                for e in raw
                if isinstance(e.get("url"), str) and "watch?v=" in e["url"]
            ][:10]
            if not videos:
                return await interaction.response.send_message(
                    "❌ 검색 결과가 없습니다.", ephemeral=True
                )

            print("[videos]: ", videos)

            # Embed  View 생성
            description = "\n".join(
                f"{i+1}. {v.get('title','-')}" for i, v in enumerate(videos)
            )
            print("[description]: ", description)
            embed = Embed(
                title=f"🔍 `{url}` 검색 결과",
                description=description,
                color=0xFFC0CB,
            )
            view = SearchResultView(self, videos)
            # ! 완료 메시지
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        embed=embed, view=view, ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        embed=embed, view=view, ephemeral=True
                    )
            except Exception as e:
                print("[ERROR] interaction 응답 실패:", type(e), e)

        # ? URL 재생
        if not skip_defer:
            await interaction.response.defer(thinking=True, ephemeral=True)

        # ! 기본정보 로드
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client
        player = await YTDLSource.from_url(
            url, loop=self.bot.loop, requester=interaction.user
        )
        print(
            "[_play] url:", url, "-> title:", getattr(player, "title", None), flush=True
        )

        # ! 봇이 음성 채널에 없음
        if not voice_client:
            # ! 유저가 음성채널에 없음
            if not (ch := interaction.user.voice and interaction.user.voice.channel):
                return await interaction.followup.send(
                    "❌ 먼저 음성 채널에 들어가 있어야 합니다.", ephemeral=True
                )
            # ! 봇을 채널 연결
            voice_client = await ch.connect()

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
        state.control_view = MusicControlView(self, state)
        await self._edit_msg(state=state, embed=embed, view=state.control_view)

        # ! 메시지
        msg = await interaction.followup.send(
            f"▶ 재생: **{player.title}**", ephemeral=True
        )
        asyncio.create_task(self._auto_delete(msg, 5.0))

    async def _pause(self, interaction):
        # !기본정보 로드
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = interaction.guild.id
        state = self._get_state(guild_id)
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
        # ! embed 업데이트
        elapsed = int(time.time() - state.start_ts)
        embed = self._make_playing_embed(state.player, guild_id, elapsed)
        # ! view 재생성
        state.control_view = MusicControlView(self, state)
        await self._edit_msg(state, embed, state.control_view)
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
        # ! embed 업데이트
        elapsed = int(time.time() - state.start_ts)
        embed = self._make_playing_embed(state.player, guild_id, elapsed)
        # ! view 재생성
        state.control_view = MusicControlView(self, state)
        await self._edit_msg(state, embed, state.control_view)
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
        state.control_view = MusicHelperView(self)
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
            user = (
                f"<@{state.player.requester.id}>"
                if state.player.requester
                else "알 수 없음"
            )
            desc_lines.append(
                f"**현재 재생 중.** \n"
                f"[{state.player.title}]({state.player.webpage_url})({m:02}:{s:02})"
                f"({uploader}) - 신청자: {user}"
            )
            desc_lines.append("")  # 구분선 역할

        # 대기열 리스트
        # ── 수정 후 _show_queue: None 처리 ──
        for i, player in enumerate(state.queue, start=1):
            total = player.data.get("duration", 0)
            m, s = divmod(total, 60)
            uploader = player.data.get("uploader") or "알 수 없음"
            user = f"<@{player.requester.id}>" if player.requester else "알 수 없음"
            desc_lines.append(
                f"{i}. [{player.title}]({player.webpage_url})({m:02}:{s:02})"
                f"({uploader}) - 신청자: {user}"
            )

        embed = Embed(
            title=f"대기열 - {n}개의 곡",
            description="\n".join(desc_lines),
            color=0xFFC0CB,
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
            new_source = discord.FFmpegOpusAudio(
                audio_url, **ffmpeg_options, executable="bin\\ffmpeg.exe"
            )
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
            state.control_view = MusicHelperView(self)
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
    print("Music Cog : setup 완료!")
