import random

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select


class HelpSelect(Select):
    def __init__(self, categories: dict[str, list[tuple[str, str]]]):
        options = [
            discord.SelectOption(label=cat, description=f"{len(cmds)}개 명령어")
            for cat, cmds in categories.items()
        ]
        super().__init__(
            placeholder="카테고리를 선택해 주세요",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="help_category_select",
        )
        self.categories = categories

    async def callback(self, interaction: discord.Interaction):
        sel = self.values[0]
        cmds = self.categories.get(sel, [])
        embed = discord.Embed(title=f"📋 `{sel}` 명령어 목록", color=0xFFC0CB)
        for name, desc in cmds:
            embed.add_field(name=name, value=desc, inline=True)
        embed.set_footer(text="원하는 다른 카테고리도 선택할 수 있습니다.")
        # 메시지 수정
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(View):
    def __init__(self, categories):
        super().__init__(timeout=None)
        self.add_item(HelpSelect(categories))

    # async def on_timeout(self):
    #     # 타임아웃 시 드롭다운 비활성화
    #     for item in self.children:
    #         item.disabled = True
    #     # 원래 메시지 수정
    #     try:
    #         await self.message.edit(
    #             content="⏰ 도움말 선택 시간이 만료되었습니다.", view=self
    #         )
    #     except:
    #         pass


class HelpCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="도움", description="봇의 모든 명령어와 사용 방법을 출력합니다."
    )
    async def custom_help(self, interaction: discord.Interaction):
        # 1) 카테고리별로 명령어 정리
        categories: dict[str, list[tuple[str, str]]] = {
            "기본": [
                ("`/도움`", "봇의 모든 명령어와 사용 방법을 출력합니다."),
                ("`/기가채드`", "기가채드 이미지를 전송합니다."),
            ],
            "AI": [
                ("`/ai`", "AI 모드를 활성화/비활성화합니다."),
                ("`/ai성격 [성격]`", "AI 응답 스타일을 설정합니다."),
            ],
            "채팅": [
                ("`/채팅` [텍스트]", "봇이 대신 메시지를 전송합니다."),
                ("`/요약`", "최근 채팅 내용을 요약합니다."),
                ("`/번역 [(선택)내용]`", "최근 채팅을 한국어로 번역합니다."),
                ("`/해석 [(선택)내용]`", "최근 채팅을 해석합니다."),
            ],
            "파티": [
                ("`/파티`", "현재 생성된 파티 목록을 출력합니다."),
                ("`/파티생성 [이름]`", "새 파티를 생성합니다."),
                ("`/파티초대 [파티명] [유저명]`", "유저를 파티에 초대합니다."),
                ("`/파티해제`", "파티를 삭제합니다."),
                ("`/파티참가 [파티명]`", "파티에 참가합니다."),
                ("`/파티탈퇴`", "파티에서 탈퇴합니다."),
            ],
            "랭크": [
                ("`/솔랭`", "솔로 랭크 정보를 출력합니다."),
                ("`/자랭`", "자유 랭크 정보를 출력합니다."),
                ("`/일일랭크`", "현재 설정된 일일 랭크를 출력합니다."),
                ("`/일일랭크변경 [이름#태그]`", "일일 랭크 설정을 변경합니다."),
                ("`/일일랭크루프`", "일일 랭크 루프를 켜거나 끕니다."),
            ],
            "검색": [
                ("`/검색 [내용]`", "웹에서 최신 정보를 검색합니다."),
                ("`/질문 [내용]`", "ChatGPT에게 질문을 보냅니다."),
                ("`/신이시여 [내용]`", "정상화의 신에게 질문합니다."),
            ],
            "음악": [
                ("`/음악`", "음악 컨트롤 패널(임베드+버튼)을 표시합니다."),
                ("`/들어와`", "봇을 음성 채널에 입장시키거나 이동시킵니다."),
                ("`/재생 [URL]`", "유튜브 URL의 음악을 재생합니다."),
                ("`/볼륨 [0~200]`", "재생 중인 음악의 볼륨을 조절합니다."),
                ("`/정지`", "음악 재생을 중지하고 음성 채널에서 나갑니다."),
                ("`/일시정지`", "재생 중인 음악을 일시정지합니다."),
                ("`/다시재생`", "일시정지된 음악을 다시 재생합니다."),
            ],
            "도박": [
                (
                    "`/뿌리기 [금액] [인원]`",
                    "선착순 버튼으로 랜덤 분배 뿌리기를 진행합니다.",
                ),
                ("`/돈줘`", "매일 1번 10,000원을 받을 수 있습니다."),
                ("`/잔액`", "보유한 돈을 확인합니다."),
                ("`/순위`", "길드 내 보유 금액 순위를 확인합니다."),
                ("`/송금 [유저] [금액]`", "다른 사용자에게 돈을 송금합니다."),
                (
                    "`/가위바위보 [선택] [금액]`",
                    "가위바위보 배팅 (승: 2배, 무: 절반, 패: 전액 잃음)",
                ),
                ("`/도박 [금액]`", "30~70% 확률의 도박 (당첨: 2배, 실패: 전액 잃음)"),
                ("`/즉석복권`", "즉석복권 구매 (300원, 최대 만원 당첨)"),
                ("`/사다리 [금액]`", "3개의 사다리 중 당첨을 골라 배팅합니다."),
            ],
        }

        # 2) 첫 번째 임베드
        embed = discord.Embed(
            title="📖 도움말",
            description="카테고리를 선택하면 해당 명령어 목록을 보여드립니다.",
            color=0xFFC0CB,
        )
        for cat, cmds in categories.items():
            embed.add_field(name=cat, value=f"{len(cmds)}개 명령어", inline=True)
        embed.set_footer(text="원하는 카테고리를 아래 드롭다운에서 선택하세요.")

        view = HelpView(categories)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        sent = await interaction.original_response()
        view.message = sent

    @app_commands.command(name="기가채드", description="기가채드 이미지를 전송합니다.")
    async def giga_chad(self, interaction: discord.Interaction):
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
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(HelpCommand(bot))
    print("HelpCommand Cog : setup 완료!")
