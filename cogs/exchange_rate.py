from __future__ import annotations

from io import BytesIO
from typing import Final

import discord
import matplotlib
import numpy as np
from discord import app_commands
from discord.ext import commands

from api.exchange_rate import (
    DEFAULT_LOOKBACK_DAYS,
    ExchangeQuote,
    ExchangeRateConfigurationError,
    ExchangeRateError,
    SUPPORTED_CURRENCIES,
    get_exchange_quote,
)

matplotlib.use("Agg")

from matplotlib import dates as mdates
from matplotlib import pyplot as plt


def _normalize_token(value: str) -> str:
    return "".join(value.split()).upper()


class ExchangeRateCommands(commands.Cog):
    CURRENCY_ALIASES: Final[dict[str, tuple[str, ...]]] = {
        "KRW": ("KRW", "원", "원화", "한국원"),
        "USD": ("USD", "달러", "미국달러", "미화", "불"),
        "JPY": ("JPY", "엔", "엔화", "일본엔", "일본엔화"),
        "EUR": ("EUR", "유로", "EURO"),
        "GBP": ("GBP", "파운드", "영국파운드", "파운드스털링"),
        "CAD": ("CAD", "캐나다달러"),
        "CHF": ("CHF", "스위스프랑"),
        "HKD": ("HKD", "홍콩달러"),
        "AUD": ("AUD", "호주달러"),
        "SAR": ("SAR", "사우디리얄"),
        "AED": ("AED", "디르함", "UAE디르함", "아랍에미리트디르함"),
        "SGD": ("SGD", "싱가포르달러"),
        "MYR": ("MYR", "링깃", "말레이시아링깃"),
        "NZD": ("NZD", "뉴질랜드달러"),
        "CNY": ("CNY", "위안", "위안화", "중국위안"),
        "THB": ("THB", "바트", "태국바트"),
        "IDR": ("IDR", "루피아", "인도네시아루피아"),
        "PHP": ("PHP", "페소", "필리핀페소"),
        "VND": ("VND", "동", "베트남동"),
        "INR": ("INR", "루피", "인도루피"),
    }
    CURRENCY_ICONS: Final[dict[str, str]] = {
        "KRW": "🇰🇷",
        "USD": "💵",
        "JPY": "💴",
        "EUR": "💶",
        "GBP": "💷",
        "CNY": "🇨🇳",
        "CAD": "🍁",
        "AUD": "🦘",
        "CHF": "🏔️",
        "HKD": "🌆",
        "SGD": "🦁",
        "AED": "🏙️",
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.alias_map = self._build_alias_map()
        print("ExchangeRateCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> ExchangeRateCommands Cog : on ready!")

    def _build_alias_map(self) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        for code, aliases in self.CURRENCY_ALIASES.items():
            alias_map[_normalize_token(code)] = code
            for alias in aliases:
                alias_map[_normalize_token(alias)] = code
        return alias_map

    def _normalize_currency(self, raw_value: str) -> str:
        normalized = _normalize_token(raw_value)
        if normalized in self.alias_map:
            return self.alias_map[normalized]
        if normalized in SUPPORTED_CURRENCIES:
            return normalized
        raise ExchangeRateError(
            "지원하지 않는 통화입니다. 예: 원, 달러, 엔, 유로, 파운드, 위안"
        )

    @staticmethod
    def _format_rate(rate: float) -> str:
        return f"{rate:,.4f}".rstrip("0").rstrip(".")

    def _currency_icon(self, code: str) -> str:
        return self.CURRENCY_ICONS.get(code, "💱")

    def _build_trend_summary(self, quote: ExchangeQuote) -> str:
        if len(quote.chart_points) < 2:
            return "➖ 추세를 계산할 데이터가 부족합니다."

        first_rate = quote.chart_points[0].rate
        latest_rate = quote.chart_points[-1].rate
        delta = latest_rate - first_rate
        change_rate = 0.0 if first_rate == 0 else (delta / first_rate) * 100

        if abs(change_rate) < 0.05:
            return "➖ 최근 구간은 거의 보합입니다."
        if delta > 0:
            return f"📈 최근 구간은 상승 추세입니다. ({change_rate:+.2f}%)"
        return f"📉 최근 구간은 하락 추세입니다. ({change_rate:+.2f}%)"

    @staticmethod
    def _exponential_moving_average(values: list[float], window: int) -> np.ndarray | None:
        if len(values) < 2:
            return None
        series = np.array(values, dtype=float)
        alpha = 2 / (window + 1)
        ema = np.empty_like(series)
        ema[0] = series[0]
        for index in range(1, len(series)):
            ema[index] = alpha * series[index] + (1 - alpha) * ema[index - 1]
        return ema

    def _build_embed(self, quote: ExchangeQuote) -> discord.Embed:
        rate_text = (
            f"{self._currency_icon(quote.base.code)} "
            f"1 {quote.base.korean_name}({quote.base.code}) = "
            f"{self._format_rate(quote.current_rate)} "
            f"{quote.target.korean_name}({quote.target.code}) "
            f"{self._currency_icon(quote.target.code)}"
        )
        embed = discord.Embed(
            title="💱 환율 정보",
            color=discord.Color.blue(),
            description=rate_text,
        )
        embed.add_field(
            name="📅 기준일",
            value=f"{quote.basis_date:%Y-%m-%d} (한국은행 ECOS)",
            inline=False,
        )
        embed.add_field(
            name="📈 그래프",
            value=(
                f"최근 {quote.requested_days}일 추이 "
                f"({len(quote.chart_points)}개 발표일)\n"
                "파란선: 실제 환율\n"
                "초록선: EMA 7 / 주황선: EMA 30 / 분홍선: EMA 90\n"
                "초록점: 최저 / 빨간점: 최고 / 보라점: 현재"
            ),
            inline=False,
        )
        embed.add_field(
            name="🧭 추세",
            value=self._build_trend_summary(quote),
            inline=False,
        )
        embed.set_footer(text="🏦 출처: 한국은행 ECOS Open API")
        embed.set_image(url="attachment://exchange_rate_chart.png")
        return embed

    def _render_chart(self, quote: ExchangeQuote) -> BytesIO:
        dates = [point.point_date for point in quote.chart_points]
        values = [point.rate for point in quote.chart_points]
        min_index = min(range(len(values)), key=values.__getitem__)
        max_index = max(range(len(values)), key=values.__getitem__)
        current_index = len(values) - 1
        latest_value = values[-1]

        fig, ax = plt.subplots(figsize=(8.8, 4.8))
        ax.plot(
            dates,
            values,
            color="#2563EB",
            linewidth=2.2,
            label="Rate",
        )
        ax.scatter(dates, values, color="#93C5FD", s=24, zorder=2)

        moving_average_specs = [
            (7, "#10B981", "EMA 7"),
            (30, "#F59E0B", "EMA 30"),
            (90, "#EC4899", "EMA 90"),
        ]
        for window, color, label in moving_average_specs:
            moving_average = self._exponential_moving_average(values, window)
            if moving_average is None:
                continue
            ax.plot(
                dates,
                moving_average,
                color=color,
                linewidth=2,
                alpha=0.95,
                label=label,
            )

        ax.scatter(
            dates[min_index],
            values[min_index],
            color="#10B981",
            s=72,
            zorder=4,
            label="Low",
        )
        ax.scatter(
            dates[max_index],
            values[max_index],
            color="#EF4444",
            s=72,
            zorder=4,
            label="High",
        )
        ax.scatter(
            dates[current_index],
            values[current_index],
            color="#8B5CF6",
            s=76,
            zorder=5,
            label="Current",
        )
        ax.annotate(
            self._format_rate(latest_value),
            xy=(dates[-1], latest_value),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            color="#111827",
            fontsize=9,
        )
        ax.set_title(
            f"{quote.base.code}/{quote.target.code} Last {quote.requested_days} Days"
        )
        ax.set_xlabel("Date")
        ax.set_ylabel("Rate")
        ax.grid(alpha=0.25, linestyle="--")
        locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
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
        name="환율",
        description="한국은행 ECOS 기준 최신 환율과 기본 30일 그래프를 보여줍니다.",
    )
    @app_commands.describe(
        기준통화="기준 통화 (예: 달러, USD)",
        대상통화="대상 통화 (예: 원, KRW)",
        기간="그래프 기간 (일 단위, 기본 30일, 최대 365일)",
    )
    async def exchange_rate(
        self,
        interaction: discord.Interaction,
        기준통화: str,
        대상통화: str,
        기간: app_commands.Range[int, 1, 365] | None = None,
    ):
        await interaction.response.defer(thinking=True)

        try:
            base_code = self._normalize_currency(기준통화)
            target_code = self._normalize_currency(대상통화)
            quote = await get_exchange_quote(
                base_code,
                target_code,
                lookback_days=기간 or DEFAULT_LOOKBACK_DAYS,
            )
        except ExchangeRateConfigurationError as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
            return
        except ExchangeRateError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except Exception as exc:
            await interaction.followup.send(
                f"⚠️ 환율 정보를 가져오는 중 오류가 발생했습니다: {exc}",
                ephemeral=True,
            )
            return

        chart_buffer = self._render_chart(quote)
        file = discord.File(chart_buffer, filename="exchange_rate_chart.png")
        embed = self._build_embed(quote)
        await interaction.followup.send(embed=embed, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(ExchangeRateCommands(bot))
    print("ExchangeRateCommands Cog : setup 완료!")
