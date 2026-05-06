import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model
from util.message_context import (
    build_message_action_target,
    build_message_select_label,
    build_recent_message_option,
)


INTERPRET_PROMPT_ID = "pmpt_68abf98a25b481938994e409ffd1ecf20db1ff235be9e7ab"


def _build_image_content(image_url: str | None):
    if not image_url:
        return None

    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": image_url,
                }
            ],
        },
    ]


async def interpret_target(
    question: str,
    image_url: str | None,
    prompt_version: str = "8",
) -> str:
    normalized_question = question.strip()
    if image_url and not normalized_question:
        normalized_question = "첨부 이미지를 해석해줘."

    try:
        return await asyncio.to_thread(
            custom_prompt_model,
            image_content=_build_image_content(image_url),
            prompt={
                "id": INTERPRET_PROMPT_ID,
                "version": prompt_version,
                "variables": {"question": normalized_question},
            },
        )
    except Exception as e:
        return f"Error: {e}"


@app_commands.context_menu(name="메시지 해석")
async def interpret_message_context_menu(
    interaction: discord.Interaction,
    message: discord.Message,
) -> None:
    target = build_message_action_target(message)
    if not target.has_input:
        await interaction.response.send_message(
            "해석할 텍스트나 이미지가 없습니다.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    interpreted = await interpret_target(target.text, target.image_url)
    await interaction.followup.send(interpreted)


class InterpretSelect(discord.ui.Select):
    def __init__(self, options_data):
        # options_data: [{'content': 메시지내용, 'id': 메시지ID}, ...]
        options = []
        for msg in options_data:
            label = build_message_select_label(
                msg.get("content", ""),
                msg.get("image_url"),
            )
            desc = "이미지 첨부됨" if msg.get("image_url") else None
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
        preview = build_message_select_label(
            self.view.selected_message.get("content", ""),
            self.view.selected_message.get("image_url"),
        )
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

        result_message = await interpret_target(target_message, image_url)

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
    @app_commands.rename(text="텍스트", image="이미지")
    @app_commands.describe(text="해석할 텍스트 (선택)")
    @app_commands.describe(image="(선택) 함께 보낼 이미지")
    async def interpret(
        self,
        interaction: discord.Interaction,
        text: str | None = None,
        image: discord.Attachment | None = None,
    ):
        if text or image:
            await interaction.response.defer(thinking=True)
            image_url = image.url if image else None
            interpreted = await interpret_target(
                text or "",
                image_url,
                prompt_version="8",
            )
            try:
                await interaction.followup.send(interpreted)
            except Exception:
                pass
        else:
            messages_options = []
            async for message in interaction.channel.history(limit=20):
                # 봇의 메시지나 빈 내용, 그리고 '/'로 시작하는 커맨드는 제외합니다.
                if message.author == self.bot.user:
                    continue

                option = build_recent_message_option(message)
                if option is None:
                    continue

                messages_options.append(option)
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
    try:
        bot.tree.add_command(interpret_message_context_menu)
    except app_commands.CommandAlreadyRegistered:
        pass
