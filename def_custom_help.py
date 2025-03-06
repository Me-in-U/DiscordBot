import json
from datetime import datetime, time, timedelta, timezone
import random

import discord
from discord.ext import commands, tasks

from requests_gpt import image_analysis, general_purpose_model
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
            ("!참가 [파티명]", "파티에 바로 참가합니다."),
            # ("!참가 [파티명]", "파티에 참가 신청을 합니다. (초대 요청 메시지 전송)"),
            # (
            #     "!수락",
            #     "!수락 명령어를 사용하면, 최근 파티 참가 요청을 보낸 유저를 자동으로 초대합니다.",
            # ),
        ]
        # 명령어 설명 생성
        help_message = "## ℹ️ 봇 명령어 목록:\n\n"
        for command, description in commands_info:
            help_message += f"- **{command}**\n\t {description}\n"

        # 명령어 출력
        await ctx.reply(help_message)

    @commands.command(name="기가채드", help="기가채드 이미지를 전송합니다.")
    async def giga_chad(self, ctx):
        image_urls = [
            "https://i.namu.wiki/i/VZzcbIRzOFxvzAz9jXW4gLsF_SzASBb3SE4FVY1WqezMjZxQ-Tys4wmMTgVB16EDPXG8y-zvoSOx9H-JzEFwA_4LQqhRVYMnvdA6d6eg2EcyEuamO_-58gVX_k9lFeeVgNDTRCZG5cVrC5VkSeDUXA.webp",
            "https://d394jeh9729epj.cloudfront.net/8DlybC0N7CU-GGKOVEZPVDc0/ab18db66-f798-4064-a86d-9a1b250e6b78.webp",
            "https://postfiles.pstatic.net/MjAyNTAxMTFfMjky/MDAxNzM2NTk1MDEwOTM1.iBsghou0kr1LFH50J7ZaRcgl9p2O5v5hAgejdfuuQSog.O8ovlLU7S2hj4tqM2kZiihm7R6QkmjBXkEQWnAlpE_Ag.JPEG/gigachd.jpg?type=w966",
            "https://img1.daumcdn.net/thumb/R1280x0/?fname=https://t1.daumcdn.net/brunch/service/user/hxCe/image/ZQdAnaMOcQvB8imsa8Wg-u_IdoA.jpg",
            "https://www.dogdrip.net/dvs/d/25/01/12/84c65bb0050ee0697b39b99a098c9987.webp",
            "https://i.seadn.io/gae/jAXmmkmtadX3_aPgJWPBPxugC4IgfqmauBMJKcxlVVVj7cF6LtqZgo41aPv3UZGUAzoMbvslwPqMs2BcFJYsTsHxpzoclK2zQK9Efw?auto=format&dpr=1&w=1000",
            "https://ih1.redbubble.net/image.4995285836.9252/bg,f8f8f8-flat,750x,075,f-pad,750x1000,f8f8f8.jpg",
            "https://preview.redd.it/behold-the-gigachad-v0-jrkvgoagzslb1.png?width=798&format=png&auto=webp&s=67b1473b0cb3978d677610adfcf8ccc7ab512d87",
            "https://content.imageresizer.com/images/memes/GigaChad-meme-7.jpg",
            "https://uploads.dailydot.com/2023/11/GigaChad.jpg?auto=compress&fm=pjpg",
        ]
        selected_image = random.choice(image_urls)
        embed = discord.Embed(title="기가채드")
        embed.set_image(url=selected_image)
        await ctx.reply(embed=embed)


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(HelpCommand(bot))
    print("HelpCommand Cog : setup 완료!")
