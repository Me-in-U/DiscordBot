import json
from datetime import datetime, time, timedelta, timezone

from discord.ext import commands, tasks

from requests_gpt import image_analysis, send_to_chatgpt
from requests_riot import get_rank_data


class HelpCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("HelpCommand Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> HelpCommand Cog : on ready!")

    @commands.command(
        aliases=["help", "도움", "도뭉", "동움"],
        help="봇의 모든 명령어와 사용 방법을 출력합니다.",
    )
    async def custom_help(self, ctx):
        """
        봇의 명령어 목록과 설명을 출력합니다.
        """
        commands_info = [
            ("!질문 [질문 내용]", "ChatGPT에게 질문하고 답변을 받습니다."),
            ("!신이시여 [질문 내용]", "정상화의 신에게 질문하고 답변을 받습니다."),
            ("!요약 [추가 요청 사항 (선택)]", "최근 채팅 내용을 요약합니다."),
            (
                "!번역 [텍스트 (선택)]",
                "입력된 텍스트나 최근 채팅을 한국어로 번역합니다.",
            ),
            (
                "!해석 [텍스트 (선택)]",
                "입력된 텍스트나 최근 채팅의 의미를 해석합니다.",
            ),
            ("!채팅 [텍스트]", "봇이 입력된 텍스트를 대신 전송합니다."),
            ("!도움", "봇의 모든 명령어와 사용 방법을 출력합니다."),
            ("!솔랭 [닉네임#태그]", "롤 솔로랭크 데이터를 출력합니다."),
            ("!자랭 [닉네임#태그]", "롤 자유랭크 데이터를 출력합니다."),
            (
                "!일일랭크",
                "현재 자정 솔랭 출력 사용자를 출력합니다.",
            ),
            (
                "!일일랭크변경 [닉네임#태그]",
                "자정 솔랭 정보 출력을 새로운 사용자로 변경합니다.",
            ),
            (
                "!일일랭크루프 true/false",
                "자정 솔랭 출력 기능 on/off.",
            ),
            # 파티 관련 명령어 추가
            ("!파티", "현재 생성되어 있는 파티 리스트를 출력합니다."),
            (
                "!파티생성 [파티 이름]",
                "파티를 생성합니다. (비공개 카테고리, 텍스트 채널, 음성 채널 생성)",
            ),
            (
                "!초대 [@닉네임 ...]",
                "해당 파티 텍스트 채널에서 멘션된 유저에게 접근 권한을 부여합니다.",
            ),
            ("!파티해제", "해당 파티 텍스트 채널에서 파티를 해제합니다."),
            ("!참가 [파티명]", "파티에 참가 신청을 합니다. (초대 요청 메시지 전송)"),
            (
                "!수락",
                "!수락 명령어를 사용하면, 최근 파티 참가 요청을 보낸 유저를 자동으로 초대합니다.",
            ),
        ]
        # 명령어 설명 생성
        help_message = "## ℹ️ 봇 명령어 목록:\n\n"
        for command, description in commands_info:
            help_message += f"- **{command}**\n\t {description}\n"

        # 명령어 출력
        await ctx.reply(help_message)


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(HelpCommand(bot))
    print("HelpCommand Cog : setup 완료!")
