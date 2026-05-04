import asyncio
from datetime import time
import json

import discord
from discord import app_commands
from discord.ext import commands, tasks

from api.riot import get_rank_data
from bot import SONPANNO_GUILD_ID, SEOUL_TZ


from util.db import fetch_one, execute_query


class RankCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_name = None  # 게임 닉네임
        self.tag_line = None  # 게임 태그
        self.daily_rank_loop_enabled = False  # 일일 랭크 루프 상태
        # self.load_settings() calls inside cog_load
        self.update_rank_data.start()
        print("Rank Cog : init 로드 완료!")

    async def cog_load(self):
        await self.load_settings()

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> RankCommands Cog : on ready!")

    async def _get_full_settings(self):
        query = (
            "SELECT setting_value FROM setting_data WHERE setting_key = 'dailySoloRank'"
        )
        row = await fetch_one(query)
        if row and row["setting_value"]:
            val = row["setting_value"]
            return json.loads(val) if isinstance(val, str) else val
        return {}

    async def load_settings(self):
        """DB에서 초기 설정을 로드합니다."""
        data = await self._get_full_settings()
        if data:
            self.game_name = data.get("userData", {}).get("game_name", "")
            self.tag_line = data.get("userData", {}).get("tag_line", "")
            self.daily_rank_loop_enabled = data.get("loop", False)

    async def save_settings(self):
        """현재 설정을 DB에 저장합니다."""
        data = await self._get_full_settings()
        if "userData" not in data:
            data["userData"] = {}
        data["userData"]["game_name"] = self.game_name
        data["userData"]["tag_line"] = self.tag_line
        data["loop"] = self.daily_rank_loop_enabled

        query = "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = %s"
        json_str = json.dumps(data, ensure_ascii=False)
        await execute_query(query, ("dailySoloRank", json_str, json_str))

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=SEOUL_TZ))  # 매일 자정
    async def update_rank_data(self):
        """매일 자정에 랭킹 정보를 업데이트합니다."""
        target_channel = self.bot.get_channel(SONPANNO_GUILD_ID)
        if not target_channel:
            print("대상 채널을 찾을 수 없습니다.")
            return

        if self.daily_rank_loop_enabled:
            try:
                await target_channel.send(
                    "📢 새로운 하루가 시작됩니다. 일일 솔랭 정보 출력"
                )
                today_rank_data = await asyncio.to_thread(
                    get_rank_data, self.game_name, self.tag_line, "solo"
                )

                settings = await self._get_full_settings()
                yesterday_data = settings.get("yesterdayData", {})

                # 새로운 유저 확인
                if (
                    yesterday_data.get("game_name") != today_rank_data["game_name"]
                    or yesterday_data.get("tag_line") != today_rank_data["tag_line"]
                ):
                    await target_channel.send("새로운 유저가 감지되었습니다!")
                    settings["yesterdayData"] = today_rank_data
                    rank_update_message = self.print_rank_data(today_rank_data)
                else:
                    # 어제 데이터를 업데이트
                    settings["yesterdayData"] = today_rank_data
                    rank_update_message = self.print_rank_data(
                        today_rank_data, yesterday_data
                    )
                await target_channel.send(rank_update_message)

                # DB 저장
                query = "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = %s"
                json_str = json.dumps(settings, ensure_ascii=False)
                await execute_query(query, ("dailySoloRank", json_str, json_str))

            except Exception as e:
                await target_channel.send(
                    f"❌ 랭킹 정보를 업데이트하는 중 오류가 발생했습니다: {e}"
                )

    @app_commands.command(
        name="솔랭",
        description="게임 닉네임과 태그를 입력하여 솔로 랭크 정보를 출력합니다.",
    )
    @app_commands.describe(
        game_name="라이엇 게임 닉네임(예: RiotUser)", tag_line="태그라인(예: 1234)"
    )
    @app_commands.rename(game_name="닉네임", tag_line="태그")
    async def print_solo_rank(
        self, interaction: discord.Interaction, game_name: str, tag_line: str
    ):
        """솔로 랭크 정보를 출력합니다."""
        try:
            rank_data = await asyncio.to_thread(
                get_rank_data, game_name, tag_line, "solo"
            )
            await interaction.response.send_message(self.print_rank_data(rank_data))
        except ValueError:
            await interaction.response.send_message(
                "올바른 형식으로 입력해주세요. 예: !솔랭 닉네임#태그"
            )

    @app_commands.command(
        name="자랭",
        description="게임 닉네임과 태그를 입력하여 자유 랭크 정보를 출력합니다.",
    )
    @app_commands.describe(
        game_name="라이엇 게임 닉네임(예: RiotUser)", tag_line="태그라인(예: 1234)"
    )
    @app_commands.rename(game_name="닉네임", tag_line="태그")
    async def print_flex_rank(
        self, interaction: discord.Interaction, game_name: str, tag_line: str
    ):
        """자유 랭크 정보를 출력합니다."""
        try:
            rank_data = await asyncio.to_thread(
                get_rank_data, game_name, tag_line, "flex"
            )
            await interaction.response.send_message(self.print_rank_data(rank_data))
        except ValueError:
            await interaction.response.send_message(
                "올바른 형식으로 입력해주세요. 예: !자랭 닉네임#태그"
            )

    @app_commands.command(
        name="일일랭크", description="현재 설정된 자정 솔랭 정보를 출력합니다."
    )
    async def daily_rank(self, interaction: discord.Interaction):
        """현재 설정된 자정 솔랭 정보를 출력합니다."""
        if self.game_name and self.tag_line:
            await interaction.response.send_message(
                f"✅ **현재 일일솔로랭크 출력 예정 정보**\n- 닉네임: {self.game_name}\n- 태그: {self.tag_line}"
            )
        else:
            await interaction.response.send_message(
                "❌ 설정된 일일 랭크 정보가 없습니다."
            )

    @app_commands.command(
        name="일일랭크변경", description="자정 솔랭 닉네임#태그를 변경합니다."
    )
    @app_commands.describe(
        text="닉네임#태그 형식으로 입력해주세요. 예: 라이엇유저#1234"
    )
    @app_commands.rename(text="닉네임태그")
    async def update_daily_rank(self, interaction: discord.Interaction, text: str):
        """자정 솔랭 닉네임#태그를 업데이트합니다."""
        try:
            game_name, tag_line = text.strip().split("#")
            self.game_name = game_name
            self.tag_line = tag_line
            self.save_settings()
            await interaction.response.send_message(
                f"✅ **성공적으로 업데이트되었습니다.**\n새 값:\n- 닉네임: {self.game_name}\n- 태그: {self.tag_line}"
            )
        except ValueError:
            await interaction.response.send_message(
                "올바른 형식으로 입력해주세요. 예: !일일랭크변경 닉네임#태그"
            )
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ **업데이트 중 오류가 발생했습니다.**\n{str(e)}"
            )

    @app_commands.command(
        name="일일랭크루프",
        description="자정 루프 상태를 변경합니다. 예: /일일랭크루프 true/false",
    )
    @app_commands.describe(status="true 또는 false로 입력하세요.")
    @app_commands.rename(status="상태")
    async def toggle_daily_loop(self, interaction: discord.Interaction, status: str):
        """자정 루프 상태를 변경합니다."""
        try:
            if status.lower() not in ["true", "false"]:
                raise ValueError
            self.daily_rank_loop_enabled = status.lower() == "true"
            await self.save_settings()
            await interaction.response.send_message(
                f"✅ **루프 상태가 {'활성화' if self.daily_rank_loop_enabled else '비활성화'}로 변경되었습니다.**"
            )
        except ValueError:
            await interaction.response.send_message(
                "올바른 형식으로 입력해주세요. 예: !일일랭크루프 true/false"
            )
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ **루프 상태 변경 중 오류가 발생했습니다.**\n{str(e)}"
            )

    def print_rank_data(self, data, yesterday_data=None):
        """랭킹 데이터를 출력합니다."""
        message = f'## "{data["game_name"]}#{data["tag_line"]}" {data["rank_type_kor"]} 정보\n'
        message += (
            f"티어: {data['tier']} {data['rank']} {data['league_points']}포인트\n"
        )
        message += f"승리: {data['wins']} ({data['win_rate']:.2f}%)\n"
        message += f"패배: {data['losses']}\n"

        if yesterday_data:
            changes = []
            if data["tier"] != yesterday_data["tier"]:
                changes.append(f"티어: {yesterday_data['tier']} -> {data['tier']}")
            if data["league_points"] != yesterday_data["league_points"]:
                changes.append(
                    f"포인트: {yesterday_data['league_points']} -> {data['league_points']}"
                )
            if data["wins"] != yesterday_data["wins"]:
                changes.append(f"승리: {yesterday_data['wins']} -> {data['wins']}")
            if data["losses"] != yesterday_data["losses"]:
                changes.append(f"패배: {yesterday_data['losses']} -> {data['losses']}")
            if changes:
                message += "\n📈 변경된 점:\n" + "\n".join(changes)
            else:
                return f'## "{data["game_name"]}#{data["tag_line"]}" {data["rank_type_kor"]} 정보\n - 📈어제와 랭크 데이터 변화가 없습니다.'

        return message


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(RankCommands(bot))
    print("Rank Cog : setup 완료!")
