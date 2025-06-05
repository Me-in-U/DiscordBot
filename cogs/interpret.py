import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import general_purpose_model, reasoning_model


class InterpretSelect(discord.ui.Select):
    def __init__(self, options_data):
        # options_data: [{'content': 메시지내용, 'id': 메시지ID}, ...]
        options = []
        for msg in options_data:
            label = msg["content"][:50] + ("..." if len(msg["content"]) > 50 else "")
            options.append(discord.SelectOption(label=label, value=str(msg["id"])))
        super().__init__(
            placeholder="최근 메시지 중 해석할 내용을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        # 선택 시 defer 응답을 먼저 해야 상호작용 실패를 방지합니다.
        # await interaction.response.defer(thinking=True)

        # 선택 시 thinking 대기 없이 바로 메시지 수정
        selected_id = self.values[0]
        # view.option_mapping 에서 content(문자열)만 꺼냅니다.
        self.view.selected_message = self.view.option_mapping.get(selected_id, "")

        # 해석 진행중…으로 메시지를 수정 (뷰 해제)
        await interaction.response.edit_message(
            content=f"{self.view.selected_message}에 대한 해석 진행중...", view=None
        )
        # 실제 해석 로직을 실행 interpret_callback 호출
        await self.view.interpret_callback(interaction)


class InterpretSelectView(discord.ui.View):
    def __init__(self, options_data):
        super().__init__(timeout=60)
        self.selected_message = None
        self.option_mapping = {str(msg["id"]): msg["content"] for msg in options_data}
        self.add_item(InterpretSelect(options_data))
        self.original_message: discord.Message | None = (
            None  # 실제 discord.Message 객체를 저장
        )

    async def interpret_callback(self, interaction: discord.Interaction):
        if not self.selected_message:
            # 선택 없이 callback 되면 경고 메시지
            await interaction.followup.send(
                "먼저 해석할 메시지를 선택해주세요.", ephemeral=True
            )
            return

        # 뷰가 달린 메시지를 수정
        await self.original_message.edit(content="해석 진행중...", view=None)
        messages = [
            {
                "role": "developer",
                "content": (
                    "당신은 문장 해석 전문가입니다. "
                    "대화 내용의 의미나 숨겨진 뜻이 있을 경우 찾아서 해석해주세요. "
                    "숨겨진 의미나 뜻이 없으면 굳이 언급하지 않아도 됩니다."
                ),
            },
            {
                "role": "developer",
                "content": f"해석할 내용:\n{self.selected_message}",
            },
        ]
        try:
            result = reasoning_model(messages)
        except Exception as e:
            result = f"Error: {e}"
        try:
            await self.original_message.edit(content=result, view=None)
        except Exception:
            pass
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                child.label = "기간만료!"
                child.style = discord.ButtonStyle.danger
        if self.original_message:
            try:
                await self.original_message.edit(
                    content="1분 이내에 해석하지 않으셔서 작업이 취소되었습니다.",
                    view=None,
                )
            except Exception:
                pass

            await asyncio.sleep(30)
            # original_message가 discord.Message인지 확인 후 삭제
            if isinstance(self.original_message, discord.Message):
                try:
                    await self.original_message.delete()
                except discord.NotFound:
                    pass


class InterpretCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        pass

    @app_commands.command(
        name="해석",
        description="텍스트를 입력하면 바로 해석, 미입력 시 최근 채팅을 선택하여 해석합니다.",
    )
    @app_commands.describe(text="해석할 텍스트 (선택)")
    @app_commands.describe(image="(선택) 함께 보낼 이미지")
    async def interpret(
        self,
        interaction: discord.Interaction,
        text: str | None = None,
        image: discord.Attachment | None = None,
    ):
        if text:
            image_url = image.url if image else None
            messages = [
                {
                    "role": "developer",
                    "content": (
                        "당신은 문장 해석 전문가입니다. "
                        "대화 내용의 의미나 숨겨진 뜻이 있을 경우 찾아서 해석해주세요. "
                        "숨겨진 의미나 뜻이 없으면 굳이 언급하지 않아도 됩니다."
                    ),
                },
                {
                    "role": "developer",
                    "content": f"해석할 내용:\n{text.strip()}",
                },
            ]
            if image_url:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"{interaction.user.name}의 질문 : {text.strip()}",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": image_url,
                                },
                            },
                        ],
                    },
                )
            else:
                messages.append(
                    {
                        "role": "user",
                        "content": f"{interaction.user.name}의 질문 : {text.strip()}",
                    },
                )
            try:
                if image_url:
                    interpreted = general_purpose_model(
                        messages,
                        model="gpt-4.1-nano",
                        temperature=0.6,
                    )
                else:
                    interpreted = reasoning_model(messages)
            except Exception as e:
                interpreted = f"Error: {e}"
            try:
                await interaction.followup.send(interpreted)
            except Exception:
                pass
        else:
            messages_options = []
            async for message in interaction.channel.history(limit=20):
                # 봇의 메시지나 빈 내용, 그리고 '/'로 시작하는 커맨드는 제외합니다.
                if (
                    message.author != self.bot.user
                    and message.content
                    and not message.content.startswith("/")
                ):
                    messages_options.append(
                        {"content": message.content, "id": message.id}
                    )
                    if len(messages_options) >= 20:
                        break
            if not messages_options:
                try:
                    await interaction.response.send_message(
                        "**해석할 메시지를 찾지 못했습니다.**"
                    )
                except Exception:
                    pass
                return
            view = InterpretSelectView(messages_options)
            # 슬래시 상호작용에 대한 첫 번째 응답
            try:
                await interaction.response.send_message(
                    content="아래 선택 메뉴에서 해석할 메시지를 선택하면 자동으로 해석이 진행됩니다.",
                    view=view,
                )
            except Exception:
                return
            # 실제로 채널에 올라간 discord.Message 객체를 가져와서 original_message에 저장
            sent_msg = await interaction.original_response()
            view.original_message = sent_msg


async def setup(bot):
    await bot.add_cog(InterpretCommands(bot))
