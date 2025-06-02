import asyncio

import discord
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
        selected_id = self.values[0]
        self.view.selected_message = self.view.option_mapping.get(selected_id, "")
        await self.view.interpret_callback(interaction)


class InterpretSelectView(discord.ui.View):
    def __init__(self, options_data):
        super().__init__(timeout=60)
        self.selected_message = None
        self.option_mapping = {str(msg["id"]): msg["content"] for msg in options_data}
        self.add_item(InterpretSelect(options_data))
        self.original_message = None

    async def interpret_callback(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        if not self.selected_message:
            try:
                await interaction.followup.send(
                    "먼저 해석할 메시지를 선택해주세요.", ephemeral=True
                )
            except Exception:
                pass
            return
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

    @commands.command(
        aliases=["해석"],
        help="이전 채팅 내용을 해석하거나 '!해석 [문장]' 형식으로 해석합니다.",
    )
    async def interpret(self, ctx, *, text: str = None):
        if text:
            target_message = text.strip()
            image_url = None
            if ctx.message.attachments:
                image_url = ctx.message.attachments[0].url
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
                    "content": f"해석할 내용:\n{target_message}",
                },
            ]
            if image_url:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"{ctx.author.name}의 질문 : {target_message}",
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
                        "content": f"{ctx.author.name}의 질문 : {target_message}",
                    },
                )
            try:
                if image_url:
                    interpreted = general_purpose_model(
                        messages,
                        model="gpt-4o-mini",
                        temperature=0.6,
                    )
                else:
                    interpreted = reasoning_model(messages)
            except Exception as e:
                interpreted = f"Error: {e}"
            try:
                await ctx.reply(interpreted)
            except Exception:
                pass
        else:
            messages_options = []
            async for message in ctx.channel.history(limit=20):
                # 봇의 메시지나 빈 내용, 그리고 '!'로 시작하는 커맨드는 제외합니다.
                if (
                    message.author != self.bot.user
                    and message.content
                    and not message.content.startswith("!")
                ):
                    messages_options.append(
                        {"content": message.content, "id": message.id}
                    )
                    if len(messages_options) >= 20:
                        break
            if not messages_options:
                try:
                    await ctx.reply("**해석할 메시지를 찾지 못했습니다.**")
                except Exception:
                    pass
                return
            view = InterpretSelectView(messages_options)
            try:
                sent_msg = await ctx.reply(
                    content="아래 선택 메뉴에서 해석할 메시지를 선택하면 자동으로 해석이 진행됩니다.",
                    view=view,
                )
            except Exception:
                return
            view.original_message = sent_msg


async def setup(bot):
    await bot.add_cog(InterpretCommands(bot))
