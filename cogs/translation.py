import asyncio

import discord
from discord.ext import commands

from api.chatGPT import general_purpose_model, reasoning_model


class TranslationSelect(discord.ui.Select):
    def __init__(self, options_data):
        # options_data: [{'content': 메시지내용, 'id': 메시지ID, 'image_url': 첨부 이미지 URL (옵션)} ...]
        options = []
        for msg in options_data:
            label = msg["content"][:50] + ("..." if len(msg["content"]) > 50 else "")
            options.append(discord.SelectOption(label=label, value=str(msg["id"])))
        super().__init__(
            placeholder="최근 메시지 중 번역할 내용을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        self.view.selected_message = self.view.option_mapping.get(selected_id, {})
        await self.view.translate_callback(interaction)


class TranslationSelectView(discord.ui.View):
    def __init__(self, options_data):
        super().__init__(timeout=60)
        self.selected_message = None  # 선택된 메시지 정보 (dict: content, image_url)
        # 옵션 매핑: 메시지 ID -> {content, image_url}
        self.option_mapping = {
            str(msg["id"]): {
                "content": msg["content"],
                "image_url": msg.get("image_url"),
            }
            for msg in options_data
        }
        self.add_item(TranslationSelect(options_data))
        self.original_message = None

    async def translate_callback(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        if not self.selected_message:
            try:
                await interaction.followup.send(
                    "먼저 번역할 메시지를 선택해주세요.", ephemeral=True
                )
            except Exception:
                pass
            return
        await self.original_message.edit(content="번역 진행중...", view=None)
        target_message = self.selected_message.get("content", "")
        image_url = self.selected_message.get("image_url")
        messages = [
            {
                "role": "developer",
                "content": (
                    "당신은 전문 번역가입니다. "
                    "대화 내용을 직역보다는 자연스럽게 한국어로 번역해 주세요. "
                    "번역된 문장 이외에 추가적인 설명은 필요 없습니다."
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
                            "text": f'번역할 내용: "{target_message}"',
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
                    "content": f'번역할 내용: "{target_message}"',
                },
            )

        try:
            if image_url:
                translated_message = general_purpose_model(
                    messages, model="gpt-4o", temperature=0.5
                )
            else:
                translated_message = reasoning_model(messages)
        except Exception as e:
            translated_message = f"Error: {e}"
        try:
            await self.original_message.edit(content=translated_message, view=None)
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
                    content="1분 이내에 번역하지 않으셔서 작업이 취소되었습니다.",
                    view=self,
                )
            except Exception:
                pass
            await asyncio.sleep(30)
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

    @commands.command(
        aliases=["번역", "버녁"],
        help="이전 채팅 내용을 한국어로 번역하거나 '!번역 [문장]' 형식으로 번역합니다.",
    )
    async def translate(self, ctx, *, text: str = None):
        if text:
            target_message = text.strip()
            image_url = None
            if ctx.message.attachments:
                image_url = ctx.message.attachments[0].url
            messages = [
                {
                    "role": "developer",
                    "content": (
                        "당신은 전문 번역가입니다. "
                        "대화 내용을 직역보다는 자연스럽게 한국어로 번역해 주세요. "
                        "번역된 문장 이외에 추가적인 설명은 필요 없습니다."
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
                                "text": f'번역할 내용: "{target_message}"',
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
                        "content": f'번역할 내용: "{target_message}"',
                    },
                )
            try:
                if image_url:
                    translated_message = general_purpose_model(
                        messages, model="gpt-4o", temperature=0.5
                    )
                else:
                    translated_message = reasoning_model(messages)
            except Exception as e:
                translated_message = f"Error: {e}"
            try:
                await ctx.reply(translated_message)
            except Exception:
                pass
        else:
            messages_options = []
            async for message in ctx.channel.history(limit=20):
                if message.author != self.bot.user and message.id != ctx.message.id:
                    # '!'로 시작하는 커맨드 메시지는 제외합니다.
                    if message.content and not message.content.startswith("!"):
                        option = {"content": message.content, "id": message.id}
                        # 이미지 첨부가 있으면 함께 저장
                        if message.attachments:
                            option["image_url"] = message.attachments[0].url
                        messages_options.append(option)
                        if len(messages_options) >= 10:
                            break
            if not messages_options:
                try:
                    await ctx.reply("**번역할 메시지를 찾지 못했습니다.**")
                except Exception:
                    pass
                return
            view = TranslationSelectView(messages_options)
            try:
                sent_msg = await ctx.reply(
                    content="아래 선택 메뉴에서 번역할 메시지를 선택하면 자동으로 한국어로 번역이 진행됩니다.",
                    view=view,
                )
            except Exception:
                return
            view.original_message = sent_msg


async def setup(bot):
    await bot.add_cog(TranslationCommands(bot))
    print("TranslationCommands Cog : setup 완료!")
