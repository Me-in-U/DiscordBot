import logging

import discord

from util.logging_utils import user_error_message


logger = logging.getLogger(__name__)


class SafeView(discord.ui.View):
    """View base that reports unexpected component callback failures safely."""

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        logger.error(
            "처리되지 않은 UI 상호작용 오류: view=%s item=%s custom_id=%s",
            type(self).__name__,
            type(item).__name__,
            getattr(item, "custom_id", None),
            exc_info=(type(error), error, error.__traceback__),
        )
        message = user_error_message("상호작용 처리", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.warning(
                "UI 상호작용 오류 응답 전송 실패: view=%s",
                type(self).__name__,
                exc_info=True,
            )
