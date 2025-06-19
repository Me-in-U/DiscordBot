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
            desc = "📷 이미지 첨부됨" if msg.get("image_url") else None
            options.append(
                discord.SelectOption(
                    label=label, value=str(msg["id"]), description=desc
                )
            )
        super().__init__(
            placeholder="최근 메시지 중 해석할 내용을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        # view.option_mapping 에서 content(문자열)만 꺼냅니다.
        self.view.selected_message = self.view.option_mapping.get(selected_id, "")

        # 선택 즉시 "해석 진행중..."으로 메시지를 편집하며 뷰를 해제
        preview = self.view.selected_message["content"][:50]
        await interaction.response.edit_message(
            content=f"{preview}에 대한 해석 진행중...", view=None
        )
        # 실제 해석 로직을 실행 interpret_callback 호출
        await self.view.interpret_callback(interaction)


class InterpretSelectView(discord.ui.View):
    def __init__(self, options_data):
        super().__init__(timeout=60)
        self.selected_message = None  # 선택된 메시지 정보 (dict: content, image_url)
        # options_data로부터 {id: {"content": ..., "image_url": ...}} 매핑 생성
        self.option_mapping = {
            str(msg["id"]): {
                "content": msg["content"],
                "image_url": msg.get("image_url"),
            }
            for msg in options_data
        }
        self.add_item(InterpretSelect(options_data))
        self.original_message: discord.Message | None = None

    async def interpret_callback(self, interaction: discord.Interaction):
        # 이미 '해석 진행중...'으로 뷰가 해제된 상태이므로 interaction.response는 별도 사용하지 않음
        # API 호출 후 원본 메시지를 다시 편집
        if not self.selected_message:
            await interaction.followup.send(
                "먼저 해석할 메시지를 선택해주세요.", ephemeral=True
            )
            return

        # 뷰가 달린 메시지를 수정
        target_message = self.selected_message.get("content", "")
        image_url = self.selected_message.get("image_url")

        messages = [
            {
                "role": "developer",
                "content": (
                    "당신은 문장 해석 전문가입니다. "
                    "대화 내용의 의미나 숨겨진 뜻이 있을 경우 찾아서 해석해주세요. "
                    "숨겨진 의미나 뜻이 없으면 굳이 언급하지 않아도 됩니다."
                ),
            },
        ]

        if image_url:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f'해석할 내용: "{target_message}"',
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
                    "content": f'해석할 내용: "{target_message}"',
                },
            )

        try:
            if image_url:
                result_message = general_purpose_model(
                    messages, model="gpt-4.1-nano", temperature=0.5
                )
            else:
                result_message = reasoning_model(messages)
        except Exception as e:
            result_message = f"Error: {e}"

        # 원본 메시지를 번역 결과로 덮어쓰기
        if isinstance(self.original_message, discord.Message):
            try:
                await self.original_message.edit(content=result_message, view=None)
            except Exception:
                pass

        self.stop()

    async def on_timeout(self):
        # 타임아웃 시 모든 버튼 비활성화 + 취소 메시지로 교체
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
