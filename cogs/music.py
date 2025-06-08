# cogs/music.py
import asyncio
import discord
import yt_dlp as youtube_dl
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, button

youtube_dl.utils.bug_reports_message = lambda: ""
ytdl_format_options = {
    "format": "bestaudio/best",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}
ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream)
        )
        if "entries" in data:
            data = data["entries"][0]
        filename = data["url"] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class MusicControlView(View):
    def __init__(self, cog: "MusicCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @button(
        label="입장/이동", style=discord.ButtonStyle.primary, custom_id="music_join"
    )
    async def join_btn(self, interaction: discord.Interaction, button: Button):
        await self.cog._enter_voice(interaction)

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

    @button(label="⏹️ 정지", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: Button):
        await self.cog._stop(interaction)


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id → 현재 재생중인 player 저장
        self.current: dict[int, YTDLSource] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> Music Cog : on ready!")

    # — 버튼 클릭 콜백들 —
    async def _enter_voice(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            if not (ch := interaction.user.voice and interaction.user.voice.channel):
                return await interaction.response.send_message(
                    "❌ 먼저 음성 채널에 들어가 있어야 합니다.", ephemeral=True
                )
            vc = await ch.connect()
        else:
            if interaction.user.voice and interaction.user.voice.channel:
                await vc.move_to(interaction.user.voice.channel)
        await interaction.response.send_message("✅ 입장/이동 완료", ephemeral=True)

    async def _pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            return await interaction.response.send_message(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
        vc.pause()
        await interaction.response.send_message("⏸️ 일시정지했습니다.", ephemeral=True)

    async def _resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_paused():
            return await interaction.response.send_message(
                "❌ 일시정지된 음악이 없습니다.", ephemeral=True
            )
        vc.resume()
        await interaction.response.send_message("▶️ 다시 재생합니다.", ephemeral=True)

    async def _stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message(
                "❌ 봇이 음성채널에 없습니다.", ephemeral=True
            )
        await vc.disconnect()
        self.current.pop(interaction.guild.id, None)
        await interaction.response.send_message("⏹️ 정지하고 나갑니다.", ephemeral=True)

    # — UI 버튼을 띄우는 슬래시 커맨드 —
    @app_commands.command(
        name="음악", description="음악 재생 상태와 컨트롤 버튼을 보여줍니다."
    )
    async def 음악(self, interaction: discord.Interaction):
        player = self.current.get(interaction.guild.id)
        embed = discord.Embed(title="🎵 음악 컨트롤", color=discord.Color.blurple())
        embed.add_field(
            name="현재 재생 중", value=player.title if player else "없음", inline=False
        )

        view = MusicControlView(self)
        await interaction.response.send_message(embed=embed, view=view)

    # — 기존 슬래시 재생 명령들 —
    @app_commands.command(name="들어와", description="음성 채널에 들어옵니다.")
    async def 들어와(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            if not (ch := interaction.user.voice and interaction.user.voice.channel):
                return await interaction.response.send_message(
                    "❌ 먼저 음성 채널에 들어가 있어야 합니다.", ephemeral=True
                )
            await ch.connect()
            return await interaction.response.send_message(
                f"✅ `{ch.name}` 채널에 입장했습니다."
            )
        # 이미 연결되어 있으면 이동만
        if interaction.user.voice and interaction.user.voice.channel:
            await vc.move_to(interaction.user.voice.channel)
            return await interaction.response.send_message(
                f"➡ `{interaction.user.voice.channel.name}` 으로 이동했습니다."
            )
        await interaction.response.send_message(
            "❌ 연결할 음성 채널을 찾을 수 없습니다.", ephemeral=True
        )

    @app_commands.command(name="재생", description="유튜브 URL을 재생합니다.")
    @app_commands.describe(url="재생할 유튜브 URL")
    async def 재생(self, interaction: discord.Interaction, url: str):
        vc = interaction.guild.voice_client
        if not vc:
            if not (ch := interaction.user.voice and interaction.user.voice.channel):
                return await interaction.response.send_message(
                    "❌ 먼저 음성 채널에 들어가 있어야 합니다.", ephemeral=True
                )
            vc = await ch.connect()

        await interaction.response.defer(thinking=True)
        player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
        if vc.is_playing():
            vc.stop()
        vc.play(player, after=lambda e: print(f"Player error: {e}") if e else None)
        self.current[interaction.guild.id] = player
        await interaction.followup.send(f"▶ Now playing: **{player.title}**")

    @app_commands.command(name="볼륨", description="볼륨을 설정합니다.")
    @app_commands.describe(퍼센트="0~200 사이의 값을 입력하세요.")
    async def 볼륨(self, interaction: discord.Interaction, 퍼센트: int):
        vc = interaction.guild.voice_client
        if not vc or not vc.source:
            return await interaction.response.send_message(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
        퍼센트 = max(0, min(퍼센트, 200))
        vc.source.volume = 퍼센트 / 100
        await interaction.response.send_message(
            f"🔊 볼륨을 {퍼센트}%로 변경했습니다.", ephemeral=True
        )

    @app_commands.command(name="정지", description="음악을 정지하고 채널에서 나갑니다.")
    async def 정지(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message(
                "❌ 봇이 연결되어 있지 않습니다.", ephemeral=True
            )
        await vc.disconnect()
        self.current.pop(interaction.guild.id, None)
        await interaction.response.send_message("⏹️ 재생을 중지하고 나갑니다.")

    @app_commands.command(name="일시정지", description="음악을 일시정지합니다.")
    async def 일시정지(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            return await interaction.response.send_message(
                "❌ 재생 중인 음악이 없습니다.", ephemeral=True
            )
        vc.pause()
        await interaction.response.send_message("⏸️ 음악을 일시정지했습니다.")

    @app_commands.command(
        name="다시재생", description="일시정지된 음악을 다시 재생합니다."
    )
    async def 다시재생(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_paused():
            return await interaction.response.send_message(
                "❌ 일시정지된 음악이 없습니다.", ephemeral=True
            )
        vc.resume()
        await interaction.response.send_message("▶️ 음악을 다시 재생합니다.")


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
    print("Music Cog : setup 완료!")
