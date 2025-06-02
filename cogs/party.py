import discord
from discord import app_commands
from discord.ext import commands


class Party(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.bot.PARTY_LIST는 봇 초기화 시 빈 딕셔너리로 설정되어 있어야 합니다.
        # 예: DISCORD_CLIENT.PARTY_LIST = {}
        self.join_requests = {}
        print("Party Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT on_ready() -> Party Cog : on ready!")

    @app_commands.command(
        name="파티", description="현재 생성되어있는 파티 리스트를 출력합니다."
    )
    async def list_party(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        if guild_id not in self.bot.PARTY_LIST or not self.bot.PARTY_LIST[guild_id]:
            await interaction.response.send_message("현재 생성된 파티가 없습니다.")
            return

        msg = "### 현재 생성된 파티 목록:\n"
        for category in self.bot.PARTY_LIST[guild_id]:
            # 파티 이름 추출 ("-파티" 접미사 제거)
            party_name = category.name.rstrip("-파티")
            # category의 overwrites에서 discord.Member 객체 중 view_channel 권한이 True인 멤버 수 계산 (봇 제외)
            individual_members = []
            for target, overwrite in category.overwrites.items():
                if isinstance(target, discord.Member):
                    if overwrite.view_channel is True and not target.bot:
                        individual_members.append(target)
            member_count = len(individual_members)
            msg += f"- {party_name} ({member_count}명)\n"
        await interaction.response.send_message(msg.strip())

    @app_commands.command(
        name="파티생성",
        description="비공개 카테고리, 텍스트 채널, 음성 채널을 생성하고, 명령어를 친 유저에게만 접근 권한을 부여합니다.",
    )
    @app_commands.describe(party_name="생성할 파티 이름을 입력하세요.")
    async def create_party(self, interaction: discord.Interaction, party_name: str):
        if not party_name:
            await interaction.response.send_message("파티 이름을 입력해 주세요.")
            return

        guild_id = interaction.guild.id
        if guild_id not in self.bot.PARTY_LIST:
            self.bot.PARTY_LIST[guild_id] = []

        target_category_name = f"{party_name}-파티"
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

        try:
            # 파티용 카테고리 생성 (카테고리 이름에 "-파티" 접미사 추가)
            category = await interaction.guild.create_category(
                name=target_category_name, overwrites=overwrites
            )
            # 카테고리 내 텍스트 채널 생성 (예: "-채팅o" 접미사)
            text_channel = await category.create_text_channel(
                name=f"{party_name}-채팅o", overwrites=overwrites
            )
            # 카테고리 내 음성 채널 생성 (예: "-음성o" 접미사)
            voice_channel = await category.create_voice_channel(
                name=f"{party_name}-음성o", overwrites=overwrites
            )
            # 해당 서버의 PARTY_LIST에 생성된 카테고리 추가
            self.bot.PARTY_LIST[guild_id].append(category)

            await interaction.response.send_message(
                f"### 파티 **'{party_name}'**가 생성되었습니다.\n"
                f"- 텍스트 채널: {text_channel.mention}\n"
                f"- 음성 채널: {voice_channel.mention}"
            )
        except Exception as e:
            await interaction.response.send_message(
                f"채널 생성 중 오류가 발생했습니다: {e}"
            )

    @app_commands.command(
        name="초대",
        description="해당 파티 텍스트 채널에서 멘션된 유저에게 접근 권한을 부여합니다.",
    )
    @app_commands.describe(member="초대할 멤버를 선택하세요.")
    async def invite_party(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        if not interaction.channel.name.endswith("-채팅o"):
            await interaction.response.send_message(
                "파티 채널에서만 가능한 명령어 입니다."
            )
            return
        if not member:
            await interaction.response.send_message("초대할 멤버를 멘션해주세요.")
            return

        category = interaction.channel.category
        if category is None:
            await interaction.response.send_message(
                "현재 채널이 카테고리에 속해 있지 않습니다."
            )
            return

        for member in interaction.message.mentions:
            try:
                await category.set_permissions(
                    member,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, connect=True, speak=True
                    ),
                )
                for channel in category.channels:
                    await channel.set_permissions(
                        member,
                        overwrite=discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            connect=True,
                            speak=True,
                        ),
                    )
            except Exception as e:
                print(f"{member}의 권한 업데이트 중 오류 발생: {e}")
        await interaction.response.send_message("초대가 완료되었습니다.")

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
        except Exception:
            pass

        for channel in category.channels:
            try:
                await channel.delete()
            except Exception as e:
                print(f"채널 {channel.name} 삭제 중 오류: {e}")
        try:
            await category.delete()
        except Exception as e:
            await interaction.response.send_message(
                f"카테고리 삭제 중 오류가 발생했습니다: {e}"
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
        except Exception:
            pass

    @app_commands.command(name="참가", description="파티에 참가합니다.")
    @app_commands.describe(party_name="참가할 파티 이름을 입력하세요.")
    async def join_party(self, interaction: discord.Interaction, party_name: str):
        if party_name is None:
            await interaction.response.send_message("파티 이름을 입력해 주세요.")
            return

        target_name = f"{party_name}-파티"
        guild_id = interaction.guild.id
        target_category = None
        if guild_id in self.bot.PARTY_LIST:
            for category in self.bot.PARTY_LIST[guild_id]:
                if category.name == target_name:
                    target_category = category
                    break
        if target_category is None:
            await interaction.response.send_message("존재하지 않는 파티입니다.")
            return

        # 카테고리의 overwrites에서 개별적으로 추가된 멤버들을 확인 (관리자 포함)
        individual_members = []
        for target, overwrite in target_category.overwrites.items():
            if isinstance(target, discord.Member):
                if overwrite.view_channel is True and not target.bot:
                    individual_members.append(target)
        if interaction.user in individual_members:
            await interaction.response.send_message("이미 참가한 파티입니다.")
            return

        text_channel = None
        for ch in target_category.channels:
            if isinstance(ch, discord.TextChannel) and ch.name.endswith("-채팅o"):
                text_channel = ch
                break
        if text_channel is None:
            await interaction.response.send_message(
                "해당 파티의 텍스트 채널을 찾을 수 없습니다."
            )
            return

        try:
            # 파티에 참가할 수 있도록 명시적으로 권한 부여
            await target_category.set_permissions(
                interaction.user,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, connect=True, speak=True
                ),
            )
            for channel in target_category.channels:
                await channel.set_permissions(
                    interaction.user,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        connect=True,
                        speak=True,
                    ),
                )
            await interaction.response.send_message(
                f"{interaction.user.mention}님, '{party_name}' 파티에 참여하셨습니다."
            )
        except Exception as e:
            await interaction.response.send_message(
                f"파티 참가 중 오류가 발생했습니다: {e}"
            )

        # 기존 파티 참가 요청 메시지 (참가 요청 기능)
        # self.join_requests[text_channel.id] = ctx.author
        # await text_channel.send(
        #     f"{ctx.author.mention}가 파티참가를 원합니다. \n '!수락'을 입력하거나 '!초대 {ctx.author.mention}'를 입력하면 파티에 추가됩니다."
        # )
        # await ctx.reply("파티 참가 요청이 전송되었습니다.")

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


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(Party(bot))
    print("Party Cog : setup 완료!")
