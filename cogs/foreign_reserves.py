from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

import discord
import matplotlib
import numpy as np
from discord import app_commands
from discord.ext import commands

from api.foreign_reserves import (
    DEFAULT_LOOKBACK_MONTHS,
    ForeignReservesConfigurationError,
    ForeignReservesError,
    ForeignReservesPoint,
    ForeignReservesStat,
    format_foreign_reserves_cycle,
    get_foreign_reserves,
)

matplotlib.use("Agg")

from matplotlib import dates as mdates
from matplotlib import pyplot as plt


def _format_decimal(value: Decimal, quantize: str = "0.1") -> str:
    normalized = value.quantize(Decimal(quantize), rounding=ROUND_HALF_UP)
    return f"{normalized:,}"


class ForeignReservesCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("ForeignReservesCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> ForeignReservesCommands Cog : on ready!")

    def _build_change_summary(self, points: list[ForeignReservesPoint]) -> str:
        if len(points) < 2:
            return "➖ 비교할 이전 월 데이터가 부족합니다."

        prev_value = points[-2].amount_okr_usd
        latest_value = points[-1].amount_okr_usd
        delta = latest_value - prev_value
        ratio = Decimal("0") if prev_value == 0 else (delta / prev_value) * Decimal("100")

        if delta == 0:
            return "➖ 전월과 동일합니다."

        direction = "증가" if delta > 0 else "감소"
        icon = "📈" if delta > 0 else "📉"
        return (
            f"{icon} 전월 대비 {direction}: "
            f"{_format_decimal(abs(delta))}억 달러 "
            f"({ratio.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):+,.2f}%)"
        )

    def _build_trend_summary(self, points: list[ForeignReservesPoint]) -> str:
        if len(points) < 2:
            return "➖ 추세를 계산할 데이터가 부족합니다."

        first_value = points[0].amount_okr_usd
        latest_value = points[-1].amount_okr_usd
        delta = latest_value - first_value
        ratio = Decimal("0") if first_value == 0 else (delta / first_value) * Decimal("100")

        if abs(ratio) < Decimal("0.05"):
            return "➖ 최근 구간은 거의 보합입니다."
        if delta > 0:
            return (
                f"📈 최근 {len(points)}개월 흐름은 상승 추세입니다. "
                f"({ratio.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):+,.2f}%)"
            )
        return (
            f"📉 최근 {len(points)}개월 흐름은 하락 추세입니다. "
            f"({ratio.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):+,.2f}%)"
        )

    def _build_embed(self, stat: ForeignReservesStat) -> discord.Embed:
        basis_cycle = format_foreign_reserves_cycle(stat.basis_cycle)
        amount_okr_usd = _format_decimal(stat.amount_okr_usd)
        raw_value = f"{stat.raw_value_million_usd:,}"

        embed = discord.Embed(
            title="💰 외환보유액",
            color=discord.Color.gold(),
            description=f"대한민국 외환보유액은 **{amount_okr_usd}억 달러**입니다.",
        )
        embed.add_field(name="📅 기준월", value=basis_cycle, inline=True)
        embed.add_field(name="🏷️ 분류", value=stat.class_name, inline=True)
        embed.add_field(
            name="📦 원본값",
            value=f"{raw_value} {stat.unit_name}",
            inline=False,
        )
        embed.add_field(
            name="📉 그래프",
            value=(
                f"최근 {stat.requested_months}개월 추이 "
                f"({len(stat.chart_points)}개 월별 데이터)\n"
                "파란선: 실제 값 / 주황 점선: 추세선"
            ),
            inline=False,
        )
        embed.add_field(
            name="↕️ 전월 대비",
            value=self._build_change_summary(stat.chart_points),
            inline=False,
        )
        embed.add_field(
            name="🧭 추세",
            value=self._build_trend_summary(stat.chart_points),
            inline=False,
        )
        embed.set_footer(text="🏦 출처: 한국은행 ECOS Open API")
        embed.set_image(url="attachment://foreign_reserves_chart.png")
        return embed

    def _render_chart(self, stat: ForeignReservesStat) -> BytesIO:
        dates = [point.point_date for point in stat.chart_points]
        values = [float(point.amount_okr_usd) for point in stat.chart_points]
        latest_value = values[-1]

        fig, ax = plt.subplots(figsize=(8.8, 4.8))
        ax.plot(
            dates,
            values,
            color="#2563EB",
            linewidth=2.2,
            marker="o",
            markersize=4.5,
            label="Reserves",
        )

        if len(values) >= 2:
            x_index = np.arange(len(values))
            trend_values = np.poly1d(np.polyfit(x_index, values, 1))(x_index)
            ax.plot(
                dates,
                trend_values,
                color="#F59E0B",
                linewidth=2,
                linestyle="--",
                alpha=0.95,
                label="Trend",
            )

        ax.scatter(dates[-1], latest_value, color="#DC2626", s=60, zorder=3)
        ax.annotate(
            _format_decimal(Decimal(str(latest_value))),
            xy=(dates[-1], latest_value),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            color="#111827",
            fontsize=9,
        )
        ax.set_title(f"KR Foreign Reserves Last {stat.requested_months} Months")
        ax.set_xlabel("Month")
        ax.set_ylabel("100M USD")
        ax.grid(alpha=0.25, linestyle="--")
        locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.legend(frameon=False, loc="best")
        fig.tight_layout()
        fig.autofmt_xdate(rotation=35, ha="right")

        image = BytesIO()
        fig.savefig(image, format="png", dpi=180, bbox_inches="tight")
        plt.close(fig)
        image.seek(0)
        return image

    @app_commands.command(
        name="외환보유액",
        description="한국은행 ECOS 기준 최신 외환보유액과 기본 12개월 그래프를 보여줍니다.",
    )
    @app_commands.describe(
        기간="그래프 기간 (개월 단위, 기본 12개월, 최대 60개월)",
    )
    async def foreign_reserves(
        self,
        interaction: discord.Interaction,
        기간: app_commands.Range[int, 1, 60] | None = None,
    ):
        await interaction.response.defer(thinking=True)

        try:
            stat = await get_foreign_reserves(
                lookback_months=기간 or DEFAULT_LOOKBACK_MONTHS
            )
        except ForeignReservesConfigurationError as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
            return
        except ForeignReservesError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except Exception as exc:
            await interaction.followup.send(
                f"⚠️ 외환보유액을 가져오는 중 오류가 발생했습니다: {exc}",
                ephemeral=True,
            )
            return

        embed = self._build_embed(stat)
        chart_buffer = self._render_chart(stat)
        file = discord.File(chart_buffer, filename="foreign_reserves_chart.png")
        await interaction.followup.send(embed=embed, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(ForeignReservesCommands(bot))
    print("ForeignReservesCommands Cog : setup 완료!")
