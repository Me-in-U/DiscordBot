import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model
from common.openai_prompt import build_prompt, build_single_image_content
from util.message_context import (
    build_message_action_target,
    build_message_select_label,
    build_recent_message_option,
)


TRANSLATION_PROMPT_ID = "pmpt_68ac23cf2e6c81969b355cc2d2ab11600ddeea74b62910b3"
TRANSLATION_PROMPT_VERSION = "6"


async def translate_target(
    target_message: str,
    image_url: str | None,
    prompt_version: str = TRANSLATION_PROMPT_VERSION,
) -> str:
    normalized_message = target_message.strip()
    if image_url and not normalized_message:
        normalized_message = "첨부 이미지의 텍스트나 내용을 한국어로 번역해줘."

    try:
        return await asyncio.to_thread(
            custom_prompt_model,
            image_content=build_single_image_content(image_url),
            prompt=build_prompt(
                TRANSLATION_PROMPT_ID,
                prompt_version,
                {"target_message": normalized_message},
            ),
        )
    except Exception as e:
        return f"Error: {e}"


@app_commands.context_menu(name="메시지 번역")
async def translate_message_context_menu(
    interaction: discord.Interaction,
    message: discord.Message,
) -> None:
    target = build_message_action_target(message)
    if not target.has_input:
        await interaction.response.send_message(
            "번역할 텍스트나 이미지가 없습니다.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    translated_message = await translate_target(target.text, target.image_url)
    await interaction.followup.send(translated_message)


class TranslationSelect(discord.ui.Select):
    def __init__(self, options_data):
        # options_data: [{'content': 메시지내용, 'id': 메시지ID, 'image_url': 첨부 이미지 URL (옵션)} ...]
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
            placeholder="최근 메시지 중 번역할 내용을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        # 선택된 메시지 ID를 꺼내서, view.selected_message에 저장
        selected_id = self.values[0]
        self.view.selected_message = self.view.option_mapping[selected_id]

        # 선택 즉시 "번역 진행중..."으로 메시지를 편집하며 뷰를 해제
        preview = build_message_select_label(
            self.view.selected_message.get("content", ""),
            self.view.selected_message.get("image_url"),
        )
        await interaction.response.edit_message(
            content=f'"{preview}"에 대한  번역 진행중...', view=None
        )

        # 실제 번역 작업을 수행
        await self.view.translate_callback(interaction)


class TranslationSelectView(discord.ui.View):
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
        self.add_item(TranslationSelect(options_data))
        self.original_message: discord.Message | None = None

    async def translate_callback(self, interaction: discord.Interaction):
        # 이미 '번역 진행중...'으로 뷰가 해제된 상태이므로 interaction.response는 별도 사용하지 않음
        # API 호출 후 원본 메시지를 다시 편집
        if not self.selected_message:
            await interaction.followup.send(
                "먼저 번역할 메시지를 선택해주세요.", ephemeral=True
            )
            return

        # 원본 메시지를 "번역 진행중..." 상태에서 최종 결과로 교체
        target_message = self.selected_message.get("content", "")
        image_url = self.selected_message.get("image_url")

        result_message = await translate_target(target_message, image_url)

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
        if isinstance(self.original_message, discord.Message):
            try:
                await self.original_message.edit(
                    content="1분 이내에 번역하지 않으셔서 작업이 취소되었습니다.",
                    view=None,
                )
            except Exception:
                pass

            await asyncio.sleep(30)
            # original_message가 discord.Message인지 확인 후 삭제
            try:
                await self.original_message.delete()
            except discord.NotFound:
                pass


class TranslationCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("TranslationCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> TranslationCommands Cog : on ready!")

    @app_commands.command(
        name="번역",
        description="텍스트를 바로 번역하거나, 지정하지 않으면 최근 채팅 중 선택하여 번역합니다.",
    )
    @app_commands.rename(text="텍스트", image="이미지")
    @app_commands.describe(
        text="번역할 텍스트를 입력하세요. (선택)",
        image="번역할 이미지를 첨부하세요. (선택)",
    )
    async def translate(
        self,
        interaction: discord.Interaction,
        text: str | None = None,
        image: discord.Attachment | None = None,
    ):
        await interaction.response.defer(thinking=True)
        if text or image:
            target_message = text.strip() if text else ""
            image_url = image.url if image else None
            translated_message = await translate_target(
                target_message,
                image_url,
                prompt_version=TRANSLATION_PROMPT_VERSION,
            )

            await interaction.followup.send(translated_message)
        else:
            messages_options = []
            async for msg in interaction.channel.history(limit=20):
                # 봇 자신의 메시지와 슬래시 커맨드 메시지는 제외
                if msg.author == self.bot.user:
                    continue

                opt = build_recent_message_option(msg)
                if opt is None:
                    continue

                messages_options.append(opt)
                if len(messages_options) >= 20:
                    break

            if not messages_options:
                await interaction.followup.send("**번역할 메시지를 찾지 못했습니다.**")
                return

            view = TranslationSelectView(messages_options)
            await interaction.followup.send(
                content="아래 선택 메뉴에서 번역할 메시지를 선택하면 자동으로 번역이 진행됩니다.",
                view=view,
            )

            # 이제 실제로 채널에 올라간 Message 객체를 얻어서 view.original_message에 저장
            sent_msg = await interaction.original_response()
            view.original_message = sent_msg


async def setup(bot):
    await bot.add_cog(TranslationCommands(bot))
    try:
        bot.tree.add_command(translate_message_context_menu)
    except app_commands.CommandAlreadyRegistered:
        pass
    print("TranslationCommands Cog : setup 완료!")
