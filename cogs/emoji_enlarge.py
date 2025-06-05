import re

import discord
from discord.ext import commands


class EmojiEnlarge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 커스텀 이모지 패턴: <:[이름]:[ID]> 또는 <a:[이름]:[ID]>
        self.emoji_pattern = re.compile(r"^(<a?:\w+:(\d+)>)$")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 봇이 보낸 메시지는 무시
        if message.author.bot:
            return

        content = message.content.strip()
        match = self.emoji_pattern.match(content)
        if not match:
            return

        full_emoji = match.group(
            1
        )  # "<:name:123456789012345678>" 혹은 "<a:name:123456789012345678>"
        emoji_id = match.group(2)  # "123456789012345678"
        print(f"EmojiEnlarge Cog : on_message -> {full_emoji} ({emoji_id})")
        # 메시지 문자열이 "<a:...>" 로 시작하면 애니메이션 GIF, 아니면 정적 PNG
        if full_emoji.startswith("<a:"):
            url = f"https://cdn.discordapp.com/emojis/{emoji_id}.gif?size=128"
        else:
            url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png?size=128"

        # Embed에 담아서 크게 표시
        embed = discord.Embed(color=0xFFC0CB)
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.avatar.url if message.author.avatar else None,
        )
        embed.set_image(url=url)

        try:
            await message.delete()
        except discord.Forbidden:
            pass

        await message.channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiEnlarge(bot))
