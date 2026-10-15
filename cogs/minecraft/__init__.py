import asyncio
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


logger = logging.getLogger(__name__)
SERVER_ADDRESS = "mc.ios.kr"
STATUS_API_URL = f"https://api.mcsrvstat.us/3/{SERVER_ADDRESS}"


class MinecraftCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="마크서버",
        description="mc.ios.kr 서버 상태와 FPS 향상, 렉 감소, 셰이더 설치 방법을 보여줍니다.",
    )
    async def minecraft_server(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        embed = discord.Embed(
            title="마인크래프트 서버",
            description=f"서버 주소: `{SERVER_ADDRESS}`",
            color=discord.Color.orange(),
        )
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "DiscordBot Minecraft server status"},
            ) as session:
                async with session.get(STATUS_API_URL) as response:
                    response.raise_for_status()
                    status = await response.json()
            if not isinstance(status, dict) or not isinstance(status.get("online"), bool):
                raise ValueError("Invalid Minecraft server status response")
            if status["online"]:
                players = status.get("players", {})
                if not isinstance(players, dict):
                    raise ValueError("Invalid Minecraft player counts")
                counts = []
                for key in ("online", "max"):
                    count = players.get(key)
                    counts.append(str(count) if type(count) is int and count >= 0 else "?")
                version = status.get("version")
                version = version[:100] if isinstance(version, str) and version else "확인 불가"
                embed.color = discord.Color.green()
                embed.add_field(name="상태", value="🟢 온라인")
                embed.add_field(name="접속 인원", value=f"{counts[0]} / {counts[1]}명")
                embed.add_field(name="서버 버전", value=version)
            else:
                embed.color = discord.Color.red()
                embed.add_field(name="상태", value="🔴 오프라인")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            logger.exception("마인크래프트 서버 상태 조회 실패: %s", SERVER_ADDRESS)
            embed.add_field(
                name="상태",
                value="⚠️ 상태 조회 실패. 잠시 후 다시 시도해 주세요.",
                inline=False,
            )

        embed.add_field(
            name="FPS 향상, 렉 감소, 셰이더 적용",
            value=(
                "1. [Fabric 설치](https://fabricmc.net/use/installer/)에서 "
                "Minecraft `26.3`을 선택해 설치\n"
                "2. [Sodium 다운로드](https://modrinth.com/mod/sodium/versions?g=26.3)에서 "
                "`mc26.3-x.x.x-fabric` 파일 다운로드 (FPS 향상, 렉 감소)\n"
                "3. [Iris 다운로드](https://modrinth.com/mod/iris/versions?g=26.3)에서 "
                "`x.x.x+26.3-fabric` 파일 다운로드 (셰이더 적용)\n"
                "4. 다운로드한 모드 파일을 `.minecraft/mods` 폴더에 넣기\n"
                "5. 런처에서 **Fabric 26.3**으로 실행"
            ),
            inline=False,
        )
        embed.add_field(
            name="SEUS PTGI 셰이더 다운로드",
            value=(
                "[다운로드 페이지](https://www.9minecraft.net/seus-ptgi-shaders-pack/)\n\n"
                "**E12**: E 시리즈 최종판, 화질 중심 / 무거움\n"
                "**HRR 2.1**: E12 기반 최적화, FPS 향상 / 비교적 가벼움\n"
                "**HRR 3.0**: 광원, 반사, 구름 개선, 추적 범위 확대 / HRR 2.1보다 무거움\n\n"
                "원하는 버전의 ZIP 파일을 압축 해제하지 않고 `.minecraft/shaderpacks`에 넣은 뒤, "
                "게임의 비디오 설정에서 셰이더 팩을 선택해 적용하세요."
            ),
            inline=False,
        )
        embed.set_footer(text="서버 상태: mcsrvstat.us | 최대 5분 전 정보일 수 있습니다.")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftCommands(bot))
