import discord
from discord.ext import commands


class Party(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.join_requests = {}
        print("Party Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT on_ready() -> Party Cog : on ready!")

    @commands.command(
        name="파티",
        help="현재 생성되어있는 파티 리스트를 출력합니다.",
    )
    async def list_party(self, ctx):
        if not self.bot.PARTY_LIST:
            await ctx.reply("현재 생성된 파티가 없습니다.")
            return

        msg = "**현재 생성된 파티 목록:**\n"
        for c in self.bot.PARTY_LIST:
            msg += f"- {c.name}\n"
        await ctx.reply(msg.strip())

    @commands.command(
        aliases=["파티생성", "파티만들기"],
        help="!파티생성 [파티 이름] 형식으로 사용하여 비공개 카테고리, 텍스트 채널, 음성 채널을 생성하고, 명령어를 친 유저에게만 접근 권한을 부여합니다.",
    )
    async def create_party(self, ctx, *, party_name: str = None):
        if party_name is None:
            await ctx.reply("파티 이름을 입력해 주세요.")
            return

        target_category_name = f"{party_name}-파티"
        # 중복 이름 검사: PARTY_LIST에 이미 동일한 이름의 카테고리가 있는지 확인
        for category in self.bot.PARTY_LIST:
            if category.name == target_category_name:
                await ctx.reply("이미 존재하는 파티입니다.")
                return

        # 권한 설정: 일반 멤버는 채널을 볼 수 없도록 하고, 명령어를 실행한 유저와 봇에게만 접근 권한 부여
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(
                view_channel=False, connect=False
            ),
            ctx.author: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, connect=True, speak=True
            ),
            self.bot.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, connect=True, speak=True
            ),
        }

        try:
            # 파티용 카테고리 생성 (카테고리 이름에 "-파티" 접미사 추가)
            category = await ctx.guild.create_category(
                name=f"{party_name}-파티", overwrites=overwrites
            )
            # 카테고리 내 텍스트 채널 생성 (예: "-파티채팅" 접미사)
            text_channel = await category.create_text_channel(
                name=f"{party_name}-파티채팅", overwrites=overwrites
            )
            # 카테고리 내 음성 채널 생성 (예: "-파티음성" 접미사)
            voice_channel = await category.create_voice_channel(
                name=f"{party_name}-파티음성", overwrites=overwrites
            )
            # PARTY_LIST 에 생성된 카테고리 추가
            self.bot.PARTY_LIST.append(category)

            await ctx.reply(
                f"### 파티 **'{party_name}'**가 생성되었습니다.\n"
                f"- 텍스트 채널: {text_channel.mention}\n"
                f"- 음성 채널: {voice_channel.mention}"
            )

        except Exception as e:
            await ctx.reply(f"채널 생성 중 오류가 발생했습니다: {e}")

    @commands.command(
        aliases=["초대", "추가"],
        help="!초대 @닉네임 @닉네임... 형식으로 사용하면, 해당 파티 텍스트 채널(예: 이름이 '-파티채팅'으로 끝남)에서 멘션된 유저에게 해당 파티(카테고리, 텍스트, 음성 채널)의 접근 권한을 부여합니다.",
    )
    async def invite_party(self, ctx):
        # 파티 텍스트 채널에서만 명령어 실행 가능 (채널 이름이 '-파티채팅'으로 끝나는지 확인)
        if not ctx.channel.name.endswith("-파티채팅"):
            await ctx.reply("파티 채널에서만 가능한 명령어 입니다.")
            return

        if not ctx.message.mentions:
            await ctx.reply("초대할 멤버를 멘션해주세요.")
            return

        # 현재 채널이 속한 카테고리 확인
        category = ctx.channel.category
        if category is None:
            await ctx.reply("현재 채널이 카테고리에 속해 있지 않습니다.")
            return

        # 각 멘션된 유저에 대해 권한 업데이트
        for member in ctx.message.mentions:
            try:
                # 카테고리의 권한을 업데이트 (하위 채널에도 적용됨)
                await category.set_permissions(
                    member,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, connect=True, speak=True
                    ),
                )
                # 각 채널별로 명시적으로 권한 부여
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

        await ctx.reply("초대가 완료되었습니다.")

    @commands.command(
        aliases=["파티해제", "해제", "해체", "파괴", "붕괴"],
        help="해당 파티 텍스트 채널에서 사용하면, 그 파티의 카테고리, 텍스트 채널, 음성 채널을 삭제합니다. 다른 채널에서 사용하면 '파티채널에서만 가능한 명령어 입니다'를 출력합니다.",
    )
    async def release_party(self, ctx):
        # 현재 채널이 파티 텍스트 채널인지 확인 (이전에 생성할 때 이름에 '-파티채팅'을 붙였음)
        if not ctx.channel.name.endswith("-파티채팅"):
            await ctx.reply("파티채널에서만 가능한 명령어 입니다")
            return

        # 현재 채널이 속한 카테고리 확인
        category = ctx.channel.category
        if category is None:
            await ctx.reply("이 채널은 카테고리에 속하지 않습니다.")
            return

        # 삭제 진행 전에 사용자에게 DM으로 결과를 알리기 위해 미리 확인 메시지 전송
        try:
            await ctx.author.send(f"'{category.name}' 파티를 해제합니다...")
        except Exception:
            pass  # DM 전송에 실패해도 계속 진행

        # 카테고리 내 모든 채널 삭제 (텍스트, 음성 모두)
        for channel in category.channels:
            try:
                await channel.delete()
            except Exception as e:
                print(f"채널 {channel.name} 삭제 중 오류: {e}")

        # 카테고리 삭제
        try:
            await category.delete()
        except Exception as e:
            await ctx.reply(f"카테고리 삭제 중 오류가 발생했습니다: {e}")
            return

        # PARTY_LIST 에서 해당 카테고리 제거 (존재하는 경우)
        if category in self.bot.PARTY_LIST:
            self.bot.PARTY_LIST.remove(category)

        # 삭제 후 DM으로 완료 메시지 전송 (현재 채널은 삭제되었으므로 DM 활용)
        try:
            await ctx.author.send("파티가 성공적으로 해제되었습니다.")
        except Exception:
            pass

    @commands.command(
        aliases=["참가", "참여", "파티참가", "파티참여", "초대요청"],
        help="!참가 [파티명] 형식으로 사용하여 파티에 참가 신청을 합니다. (이미 참가한 경우와 존재하지 않는 파티인 경우를 구분합니다.)",
    )
    async def join_party(self, ctx, *, party_name: str = None):
        if party_name is None:
            await ctx.reply("파티 이름을 입력해 주세요.")
            return

        # 생성 시 파티 카테고리 이름은 "{파티명}-파티" 로 생성됨.
        target_name = f"{party_name}-파티"
        target_category = None
        for category in self.bot.PARTY_LIST:
            if category.name == target_name:
                target_category = category
                break

        if target_category is None:
            await ctx.reply("존재하지 않는 파티입니다.")
            return

        # 참가 여부 확인: 해당 카테고리의 권한 오버라이트가 이미 설정되어 있는지 확인
        overwrite = target_category.overwrites_for(ctx.author)
        if overwrite.view_channel is True:
            await ctx.reply("이미 참가한 파티입니다.")
            return

        # 참가 요청 메시지를 파티 텍스트 채널에 전송
        text_channel = None
        for ch in target_category.channels:
            if isinstance(ch, discord.TextChannel) and ch.name.endswith("-파티채팅"):
                text_channel = ch
                break

        if text_channel is None:
            await ctx.reply("해당 파티의 텍스트 채널을 찾을 수 없습니다.")
            return

        await text_channel.send(
            f"{ctx.author.mention}가 파티참가를 원합니다. \n '!수락'을 입력하거나 '!초대 {ctx.author.mention}'를 입력하면 파티에 추가됩니다."
        )
        await ctx.reply("파티 참가 요청이 전송되었습니다.")

    @commands.command(
        name="수락",
        help="!수락 명령어를 사용하면, 최근 파티 참가 요청을 보낸 유저를 자동으로 초대합니다.",
    )
    async def accept_party(self, ctx):
        # 수락 명령어는 파티 텍스트 채널에서만 실행 가능
        if not ctx.channel.name.endswith("-파티채팅"):
            await ctx.reply("파티 채널에서만 가능한 명령어 입니다.")
            return

        # join_requests에서 해당 텍스트 채널의 최근 요청 유저를 가져옴
        self.join_requests = getattr(self, "join_requests", {})
        join_request_user = self.join_requests.get(ctx.channel.id, None)
        if join_request_user is None:
            await ctx.reply("현재 수락할 참가 요청이 없습니다.")
            return

        # 이미 참가했는지 확인
        category = ctx.channel.category
        if category is None:
            await ctx.reply("현재 채널이 카테고리에 속해 있지 않습니다.")
            return

        overwrite = category.overwrites_for(join_request_user)
        if overwrite.view_channel is True:
            await ctx.reply("해당 유저는 이미 참가한 상태입니다.")
            return

        try:
            # 해당 유저에게 접근 권한 부여 (invite_party와 유사하게 처리)
            await category.set_permissions(
                join_request_user,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, connect=True, speak=True
                ),
            )
            for channel in category.channels:
                await channel.set_permissions(
                    join_request_user,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, connect=True, speak=True
                    ),
                )
            # 수락 후, join_requests에서 제거
            self.join_requests.pop(ctx.channel.id, None)
            await ctx.reply(
                f"{join_request_user.mention}의 참가 요청이 수락되었습니다."
            )
        except Exception as e:
            await ctx.reply(f"참가 요청 수락 중 오류가 발생했습니다: {e}")


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(Party(bot))
    print("Party Cog : setup 완료!")
