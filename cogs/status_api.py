import os
import time
from datetime import datetime, timezone

from aiohttp import web
from discord.ext import commands


class StatusApi(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        # 기본 포트는 1557으로 설정, .env 등에서 API_PORT로 변경 가능
        self.port = int(os.getenv("API_PORT", 1557))
        # 미들웨어 등록: Host 헤더 검사
        self.app = web.Application(middlewares=[self.host_check_middleware])
        self.app.router.add_get("/health", self.health_handler)
        self.app.router.add_get("/", self.index_handler)
        self.runner = None
        self.site = None

    @web.middleware
    async def host_check_middleware(self, request, handler):
        """bot.ios.kr 도메인으로 들어온 요청만 처리하는 미들웨어"""
        # request.host는 'hostname:port' 또는 'hostname' 형태입니다.
        host = request.host
        hostname = host.split(":")[0]  # 포트 번호 제거

        allowed_domains = ["bot.ios.kr"]
        # 로컬 테스트가 필요하다면 아래 주석을 해제하세요
        # allowed_domains.extend(["localhost", "127.0.0.1"])

        if hostname not in allowed_domains:
            return web.Response(status=403, text="Forbidden: Invalid Host")

        return await handler(request)

    async def index_handler(self, request):
        """루트 경로 접속 시 간단한 안내 문구 반환"""
        return web.Response(text=f"Bot Status API is running on port {self.port}")

    async def health_handler(self, request):
        """봇의 상태 정보를 JSON으로 반환"""
        status = "online" if self.bot.is_ready() else "starting"

        # 봇이 참여 중인 길드 수와 총 유저 수 계산
        guild_count = len(self.bot.guilds)
        total_members = sum(len(g.members) for g in self.bot.guilds)

        # 저장된 메시지 수 계산
        message_count = 0
        if hasattr(self.bot, "USER_MESSAGES"):
            for guild_data in self.bot.USER_MESSAGES.values():
                for user_msgs in guild_data.values():
                    message_count += len(user_msgs)

        data = {
            "status": status,
            "latency_ms": round(self.bot.latency * 1000, 2),
            "uptime_s": round(time.time() - self.start_time, 2),
            "guild_count": guild_count,
            "user_count": total_members,
            "message_count": message_count,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "bot_name": str(self.bot.user) if self.bot.user else "Unknown",
        }
        return web.json_response(data)

    async def cog_load(self):
        """Cog가 로드될 때 웹 서버 시작"""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await self.site.start()
        print(f"✅ Status API Server started on port {self.port}")

    async def cog_unload(self):
        """Cog가 언로드될 때 웹 서버 종료"""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        print("❎ Status API Server stopped")


async def setup(bot):
    await bot.add_cog(StatusApi(bot))
