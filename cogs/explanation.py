import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model
from common.openai_prompt import build_prompt, build_single_image_content
from util.message_context import (
    build_message_action_target,
    build_message_select_label,
    build_recent_message_option,
    build_surrounding_message_context,
)
from util.logging_utils import log_user_error


EXPLANATION_PROMPT_ID = "pmpt_69fabdb4fa308190867e700bb0a2de160eaa5a328b9e0f83"
EXPLANATION_PROMPT_VERSION = "5"
logger = logging.getLogger(__name__)
_EXPLANATION_RESPONSE_LABEL_PATTERN = re.compile(
    r"(?i)\b(Summary|Details|Explanation|Context|Unclear|요약|설명|주요 내용|맥락|추가 맥락|불확실한 부분)\s*:"
)


def build_explanation_option_label(
    content: str,
    has_image: bool,
    max_length: int = 50,
) -> str:
    image_url = "image" if has_image else None
    return build_message_select_label(content, image_url, max_length)


def build_explanation_prompt(
    text: str,
    has_image: bool = False,
    previous_messages: str = "",
    following_messages: str = "",
    prompt_version: str = EXPLANATION_PROMPT_VERSION,
) -> dict:
    normalized_text = str(text or "").strip()
    if has_image and not normalized_text:
        normalized_text = "첨부 이미지의 내용을 설명해줘."
    elif not normalized_text:
        normalized_text = "입력된 내용을 설명해줘."

    return build_prompt(
        EXPLANATION_PROMPT_ID,
        prompt_version,
        {
            "previous_messages": str(previous_messages or "").strip(),
            "target_message": normalized_text,
            "following_messages": str(following_messages or "").strip(),
        },
    )


def format_explanation_response_for_discord(response: str) -> str:
    stripped_response = response.strip()
    if not stripped_response:
        return response
    if (
        "**요약**" in stripped_response
        or "**설명**" in stripped_response
        or "### 요약" in stripped_response
        or "### 설명" in stripped_response
    ):
        return stripped_response

    matches = list(_EXPLANATION_RESPONSE_LABEL_PATTERN.finditer(stripped_response))
    if not matches:
        return f"**설명**\n{stripped_response}"

    heading_by_label = {
        "summary": "요약",
        "요약": "요약",
        "details": "설명",
        "explanation": "설명",
        "설명": "설명",
        "주요 내용": "설명",
        "context": "맥락",
        "맥락": "맥락",
        "추가 맥락": "맥락",
        "unclear": "불확실한 부분",
        "불확실한 부분": "불확실한 부분",
    }
    sections = []
    for index, match in enumerate(matches):
        label = match.group(1).lower()
        heading = heading_by_label[label]
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else None
        content = stripped_response[start:end].strip()
        if content:
            sections.append(f"**{heading}**\n{content}")

    return "\n\n".join(sections) if sections else stripped_response


def _generate_explanation(
    text: str,
    image_url: str | None,
    previous_messages: str = "",
    following_messages: str = "",
) -> str:
    response = custom_prompt_model(
        image_content=build_single_image_content(image_url),
        prompt=build_explanation_prompt(
            text,
            has_image=bool(image_url),
            previous_messages=previous_messages,
            following_messages=following_messages,
        ),
    )
    return format_explanation_response_for_discord(response)


async def explain_target(
    text: str,
    image_url: str | None,
    previous_messages: str = "",
    following_messages: str = "",
) -> str:
    try:
        return await asyncio.to_thread(
            _generate_explanation,
            text,
            image_url,
            previous_messages,
            following_messages,
        )
    except Exception as exc:
        return log_user_error(logger, "설명", exc)


@app_commands.context_menu(name="메시지 설명")
async def explain_message_context_menu(
    interaction: discord.Interaction,
    message: discord.Message,
) -> None:
    target = build_message_action_target(message)
    if not target.has_input:
        await interaction.response.send_message(
            "설명할 텍스트나 이미지가 없습니다.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    context = await build_surrounding_message_context(
        message,
        bot_user=getattr(interaction.client, "user", None),
    )
    explained = await explain_target(
        target.text,
        target.image_url,
        previous_messages=context.previous_messages,
        following_messages=context.following_messages,
    )
    await interaction.followup.send(explained)


class ExplanationSelect(discord.ui.Select):
    def __init__(self, options_data):
        options = []
        for msg in options_data:
            label = build_explanation_option_label(
                msg.get("content", ""),
                bool(msg.get("image_url")),
            )
            desc = "이미지 첨부됨" if msg.get("image_url") else None
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(msg["id"]),
                    description=desc,
                )
            )
        super().__init__(
            placeholder="최근 메시지 중 설명할 내용을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        self.view.selected_message = self.view.option_mapping[selected_id]
        preview = build_explanation_option_label(
            self.view.selected_message.get("content", ""),
            bool(self.view.selected_message.get("image_url")),
        )
        await interaction.response.edit_message(
            content=f"{preview}에 대한 설명 진행중...",
            view=None,
        )
        await self.view.explain_callback(interaction)


class ExplanationSelectView(discord.ui.View):
    def __init__(self, options_data):
        super().__init__(timeout=60)
        self.selected_message = None
        self.option_mapping = {
            str(msg["id"]): {
                "content": msg.get("content", ""),
                "image_url": msg.get("image_url"),
                "message": msg.get("message"),
            }
            for msg in options_data
        }
        self.add_item(ExplanationSelect(options_data))
        self.original_message: discord.Message | None = None

    async def explain_callback(self, interaction: discord.Interaction):
        if not self.selected_message:
            await interaction.followup.send(
                "먼저 설명할 메시지를 선택해주세요.",
                ephemeral=True,
            )
            return

        source_message = self.selected_message.get("message")
        context = await build_surrounding_message_context(
            source_message,
            bot_user=getattr(interaction.client, "user", None),
        )

        result_message = await explain_target(
            self.selected_message.get("content", ""),
            self.selected_message.get("image_url"),
            previous_messages=context.previous_messages,
            following_messages=context.following_messages,
        )
        if isinstance(self.original_message, discord.Message):
            try:
                await self.original_message.edit(content=result_message, view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.debug("설명 결과 메시지 수정 실패", exc_info=True)

        self.stop()

    async def on_timeout(self):
        if isinstance(self.original_message, discord.Message):
            try:
                await self.original_message.edit(
                    content="1분 이내에 설명할 메시지를 선택하지 않아 작업이 취소되었습니다.",
                    view=None,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.debug("설명 선택 만료 메시지 수정 실패", exc_info=True)

            await asyncio.sleep(30)
            try:
                await self.original_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.debug("설명 선택 만료 메시지 삭제 실패", exc_info=True)


class ExplanationCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("ExplanationCommands Cog : init 로드 완료!")

    @app_commands.command(
        name="설명",
        description="텍스트나 이미지를 설명하거나, 미입력 시 최근 채팅 중 선택하여 설명합니다.",
    )
    @app_commands.rename(text="텍스트", image="이미지")
    @app_commands.describe(
        text="설명할 텍스트를 입력하세요. (선택)",
        image="설명할 이미지를 첨부하세요. (선택)",
    )
    async def explain(
        self,
        interaction: discord.Interaction,
        text: str | None = None,
        image: discord.Attachment | None = None,
    ):
        await interaction.response.defer(thinking=True)
        if text or image:
            image_url = image.url if image else None
            explained = await explain_target(text or "", image_url)
            await interaction.followup.send(explained)
            return

        messages_options = []
        async for message in interaction.channel.history(limit=20):
            if message.author == self.bot.user:
                continue

            option = build_recent_message_option(message)
            if option is None:
                continue

            option["message"] = message
            messages_options.append(option)
            if len(messages_options) >= 20:
                break

        if not messages_options:
            await interaction.followup.send("**설명할 메시지를 찾지 못했습니다.**")
            return

        view = ExplanationSelectView(messages_options)
        await interaction.followup.send(
            content="아래 선택 메뉴에서 설명할 메시지를 선택하면 자동으로 설명이 진행됩니다.",
            view=view,
        )
        sent_msg = await interaction.original_response()
        view.original_message = sent_msg


async def setup(bot):
    await bot.add_cog(ExplanationCommands(bot))
    try:
        bot.tree.add_command(explain_message_context_menu)
    except app_commands.CommandAlreadyRegistered:
        pass
    print("ExplanationCommands Cog : setup 완료!")
