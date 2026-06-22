import logging
import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, button


logger = logging.getLogger(__name__)


class JoinView(View):
    def __init__(self, party_name: str, category: discord.CategoryChannel):
        super().__init__(timeout=None)
        self.party_name = party_name
        self.category = category

    @button(
        label="파티 참가", style=discord.ButtonStyle.primary, custom_id="join_party_btn"
    )
    async def join_button(
        self, interaction: discord.Interaction, btn: discord.ui.Button
    ):
        # 이미 참가했는지 체크
        existing = [
            t
            for t, o in self.category.overwrites.items()
            if isinstance(t, discord.Member) and o.view_channel and not t.bot
        ]
        if interaction.user in existing:
            await interaction.response.send_message(
                "이미 파티에 참여 중입니다.", ephemeral=True
            )
            return

        # 권한 부여
        overwrite = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, connect=True, speak=True
        )
        await self.category.set_permissions(interaction.user, overwrite=overwrite)
        for ch in self.category.channels:
            await ch.set_permissions(interaction.user, overwrite=overwrite)

        await interaction.response.send_message(
            f"{interaction.user.mention}님, '{self.party_name}' 파티에 참여하였습니다.",
            ephemeral=False,
        )
        # ▶ 파티 채팅창에도 알림
        for ch in self.category.channels:
            if isinstance(ch, discord.TextChannel) and ch.name.endswith("-채팅o"):
                await ch.send(
                    f"🎉 {interaction.user.display_name}님이 파티에 입장했습니다."
                )
                break


class Party(commands.Cog):
    async def party_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        guild_id = interaction.guild.id
        choices: list[app_commands.Choice[str]] = []
        if guild_id in self.bot.PARTY_LIST:
            for cat in self.bot.PARTY_LIST[guild_id]:
                name = cat.name.removesuffix("-파티")
                if current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=name, value=name))
                    if len(choices) >= 25:
                        break
        if not choices:
            await interaction.response.send_message(
                "참여 가능한 파티가 없습니다.", ephemeral=True
            )
            return
        return choices

    def __init__(self, bot):
        self.bot = bot
        # self.bot.PARTY_LIST는 봇 초기화 시 빈 딕셔너리로 설정되어 있어야 합니다.
        # 예: DISCORD_CLIENT.PARTY_LIST = {}
        self.join_requests = {}
        print("Party Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> Party Cog : on ready!")

    @app_commands.command(
        name="파티", description="현재 생성되어있는 파티 리스트를 임베드로 출력합니다."
    )
    async def list_party(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        parties = self.bot.PARTY_LIST.get(guild_id, [])
        if not parties:
            return await interaction.response.send_message(
                "현재 생성된 파티가 없습니다.", ephemeral=True
            )

        embed = discord.Embed(
            title="🎉 현재 생성된 파티 목록",
            color=0xFFC0CB,
            timestamp=interaction.created_at,
        )
        for category in parties:
            party_name = category.name.rstrip("-파티")
            member_count = sum(
                1
                for t, o in category.overwrites.items()
                if isinstance(t, discord.Member) and o.view_channel and not t.bot
            )
            embed.add_field(
                name=party_name, value=f"{member_count}명 참여 중", inline=True
            )

        embed.set_footer(text=f"{len(parties)}개의 파티")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="파티생성",
        description="비공개 카테고리·채널 생성 후, 버튼으로 즉시 참가 가능하게 합니다.",
    )
    @app_commands.describe(파티명="생성할 파티 이름을 입력하세요.")
    async def create_party(self, interaction: discord.Interaction, 파티명: str):
        if not 파티명:
            await interaction.response.send_message("파티 이름을 입력해 주세요.")
            return

        guild_id = interaction.guild.id
        if guild_id not in self.bot.PARTY_LIST:
            self.bot.PARTY_LIST[guild_id] = []

        target_category_name = f"{파티명}-파티"
        # 중복 이름 검사: 해당 서버의 PARTY_LIST에 이미 동일한 이름의 카테고리가 있는지 확인
        for category in self.bot.PARTY_LIST[guild_id]:
            if category.name == target_category_name:
                await interaction.response.send_message("이미 존재하는 파티입니다.")
                return

        # 권한 설정: 일반 멤버는 채널을 볼 수 없도록 하고, 명령어 실행자와 봇에게만 접근 권한 부여
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(
                view_channel=False, connect=False
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, connect=True, speak=True
            ),
            self.bot.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, connect=True, speak=True
            ),
        }
        # 1) 카테고리 및 채널 우선 생성
        category = await interaction.guild.create_category(
            name=target_category_name, overwrites=overwrites
        )
        text_channel = await category.create_text_channel(
            name=f"{파티명}-채팅o", overwrites=overwrites, position=0
        )
        voice_channel = await category.create_voice_channel(
            name=f"{파티명}-음성o", overwrites=overwrites, position=1
        )
        self.bot.PARTY_LIST[guild_id].append(category)

        # 임베드 작성
        embed = discord.Embed(
            title=f"🎉 '{파티명}' 파티가 생성되었습니다!",
            color=0xFFC0CB,
            timestamp=interaction.created_at,
        )
        embed.add_field(name="📄 텍스트 채널", value=text_channel.mention, inline=True)
        embed.add_field(name="🔊 음성 채널", value=voice_channel.mention, inline=True)
        embed.set_footer(text="아래 버튼을 눌러 바로 파티에 참여하세요!")

        view = JoinView(파티명, category)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

        async def relocate():
            # 사이드바 순서대로 카테고리 리스트
            cats = interaction.guild.categories
            # “통화의 공간” 인덱스 찾기
            ref_idx = next(
                (i for i, c in enumerate(cats) if c.name == "일기"), len(cats)
            )
            # 새 카테고리만 해당 위치로 이동
            await category.edit(position=ref_idx)

        asyncio.create_task(relocate())

    @app_commands.command(
        name="파티초대",
        description="파티와 유저를 선택해 바로 초대합니다.",
    )
    @app_commands.describe(
        파티명="초대할 파티 이름을 선택하세요.", 멤버="초대할 멤버를 선택하세요."
    )
    @app_commands.autocomplete(파티명=party_autocomplete)
    async def invite_party(
        self, interaction: discord.Interaction, 파티명: str, 멤버: discord.Member
    ):
        # 1) 선택한 파티 찾기
        target_name = f"{파티명}-파티"
        guild_id = interaction.guild.id
        target_category = None
        for cat in self.bot.PARTY_LIST.get(guild_id, []):
            if cat.name == target_name:
                target_category = cat
                break
        if target_category is None:
            return await interaction.response.send_message(
                "존재하지 않는 파티입니다.", ephemeral=True
            )

        # 2) 이미 권한 있는지 체크
        ow = target_category.overwrites.get(멤버)
        if isinstance(ow, discord.PermissionOverwrite) and ow.view_channel:
            return await interaction.response.send_message(
                "이미 초대된 멤버입니다.", ephemeral=True
            )

        # 3) 권한 부여
        perm = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, connect=True, speak=True
        )
        await target_category.set_permissions(멤버, overwrite=perm)
        for ch in target_category.channels:
            await ch.set_permissions(멤버, overwrite=perm)

        await interaction.response.send_message(
            f"{멤버.mention}님을 '{파티명}' 파티에 초대했습니다.", ephemeral=True
        )
        # ▶ 파티 채팅창에도 알림
        for ch in target_category.channels:
            if isinstance(ch, discord.TextChannel) and ch.name.endswith("-채팅o"):
                await ch.send(f"📢 {멤버.display_name}님이 파티에 초대되었습니다.")
                break

    @app_commands.command(
        name="파티해제",
        description="해당 파티 텍스트 채널에서 사용하면, 해당 파티를 삭제합니다.",
    )
    async def release_party(self, interaction: discord.Interaction):
        if not interaction.channel.name.endswith("-채팅o"):
            await interaction.response.send_message(
                "파티채널에서만 가능한 명령어 입니다"
            )
            return

        category = interaction.channel.category
        if category is None:
            await interaction.response.send_message(
                "이 채널은 카테고리에 속하지 않습니다."
            )
            return

        try:
            await interaction.user.send(f"'{category.name}' 파티를 해제합니다...")
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("파티 해제 DM 전송 실패", exc_info=True)

        for channel in category.channels:
            try:
                await channel.delete()
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("파티 채널 삭제 실패: channel=%s", channel.name, exc_info=True)
        try:
            await category.delete()
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("파티 카테고리 삭제 실패: category=%s", category.name)
            await interaction.response.send_message(
                "⚠️ 파티 카테고리 삭제 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            )
            return

        guild_id = interaction.guild.id
        if (
            guild_id in self.bot.PARTY_LIST
            and category in self.bot.PARTY_LIST[guild_id]
        ):
            self.bot.PARTY_LIST[guild_id].remove(category)

        try:
            await interaction.user.send("파티가 성공적으로 해제되었습니다.")
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("파티 해제 완료 DM 전송 실패", exc_info=True)

    @app_commands.command(name="파티참가", description="파티에 참가합니다.")
    @app_commands.describe(파티명="참가할 파티 이름을 입력하세요.")
    @app_commands.autocomplete(파티명=party_autocomplete)
    async def join_party(self, interaction: discord.Interaction, 파티명: str):
        target_name = f"{파티명}-파티"
        guild_id = interaction.guild.id

        # 1) 카테고리 찾기
        target_category = None
        for cat in self.bot.PARTY_LIST.get(guild_id, []):
            if cat.name == target_name:
                target_category = cat
                break
        if not target_category:
            return await interaction.response.send_message(
                "존재하지 않는 파티입니다.", ephemeral=True
            )

        # 2) 이미 참가했는지 체크
        ow = target_category.overwrites.get(interaction.user)
        if isinstance(ow, discord.PermissionOverwrite) and ow.view_channel:
            return await interaction.response.send_message(
                "이미 참가한 파티입니다.", ephemeral=True
            )

        # 3) 파티 권한 부여
        perm = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, connect=True, speak=True
        )
        await target_category.set_permissions(interaction.user, overwrite=perm)
        for ch in target_category.channels:
            await ch.set_permissions(interaction.user, overwrite=perm)

        # 4) 호출 채널에 사용자에게 알림
        await interaction.response.send_message(
            f"{interaction.user.mention}님이, `{파티명}` 파티에 참여하셨습니다.",
            ephemeral=False,
        )

        # 5) 파티 텍스트 채널에 입장 공지
        for ch in target_category.channels:
            if isinstance(ch, discord.TextChannel) and ch.name.endswith("-채팅o"):
                await ch.send(
                    f"🎉 {interaction.user.display_name}님이 파티에 입장했습니다."
                )
                break

    @app_commands.command(
        name="파티원", description="개별로 추가된 파티 멤버들의 닉네임을 출력합니다."
    )
    async def party_members(self, interaction: discord.Interaction):
        # 파티 텍스트 채널에서만 실행 가능하도록 체크
        if not interaction.channel.name.endswith("-채팅o"):
            await interaction.response.send_message(
                "파티 채널에서만 가능한 명령어 입니다."
            )
            return

        category = interaction.channel.category
        if category is None:
            await interaction.response.send_message(
                "이 채널은 카테고리에 속하지 않습니다."
            )
            return

        individual_members = []
        # 카테고리의 overwrites에서 discord.Member 객체로 추가된 멤버만 필터링
        for target, overwrite in category.overwrites.items():
            if isinstance(target, discord.Member):
                if overwrite.view_channel is True and not target.bot:
                    individual_members.append(target)

        # 카테고리 이름에서 "-파티" 접미사를 제거하여 파티 이름 추출
        party_name = category.name.rstrip("-파티")
        member_count = len(individual_members)

        if member_count == 0:
            await interaction.response.send_message(
                "개별로 추가된 파티 멤버가 없습니다."
            )
            return

        result = f"**{party_name} ({member_count}명)**\n파티원:\n" + "\n".join(
            f"- {member.display_name}" for member in individual_members
        )
        await interaction.response.send_message(result)

    @app_commands.command(
        name="파티탈퇴",
        description="파티 채팅방에서 사용 시, 해당 파티에서 본인의 권한을 해제합니다.",
    )
    async def leave_party(self, interaction: discord.Interaction):
        # 1) 채널이 파티인지 확인
        category = interaction.channel.category
        if category is None or not category.name.endswith("-파티"):
            return await interaction.response.send_message(
                "파티 채팅방에서만 사용할 수 있는 명령어입니다.", ephemeral=True
            )

        # 2) 권한 제거
        try:
            await category.set_permissions(interaction.user, overwrite=None)
            for ch in category.channels:
                await ch.set_permissions(interaction.user, overwrite=None)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("파티 권한 해제 실패: category=%s", category.name)
            return await interaction.response.send_message(
                "⚠️ 파티 권한 해제 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                ephemeral=True,
            )

        # 3) 성공 안내
        await interaction.response.send_message(
            f"{interaction.user.mention}님, '{category.name.rstrip('-파티')}' 파티에서 탈퇴하셨습니다.",
            ephemeral=True,
        )
        # ▶ 파티 채팅창에도 알림
        for ch in category.channels:
            if isinstance(ch, discord.TextChannel) and ch.name.endswith("-채팅o"):
                await ch.send(
                    f"👋 {interaction.user.display_name}님이 파티에서 나갔습니다."
                )
                break


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(Party(bot))
    print("Party Cog : setup 완료!")
