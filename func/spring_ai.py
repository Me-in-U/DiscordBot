import aiohttp


async def spring_ai(DISCORD_CLIENT, message):
    # ! AI 모드 토글
    if message.content == "AI":
        if DISCORD_CLIENT.SPRING_AI_MODE:
            # AI 모드가 활성화되어 있으면 비활성화
            DISCORD_CLIENT.SPRING_AI_MODE = False
            await message.channel.send("AI 모드가 비활성화되었습니다.")
            return
        else:
            # AI 모드가 비활성화되어 있으면 활성화
            DISCORD_CLIENT.SPRING_AI_MODE = True
            await message.channel.send("AI 모드가 활성화되었습니다.")

    # ! AI모드가 활성화되어 있고, 봇이 보낸 메시지가 아니면 처리
    if not DISCORD_CLIENT.SPRING_AI_MODE or message.author == DISCORD_CLIENT.user:
        return

    url = "https://api.sonpanno.com/api/v1/discord/chat"
    payload = {
        "message": message.content,
        "convoId": DISCORD_CLIENT.CONV_ID,
    }
    # SSL 검증을 끄는 컨텍터 생성 (False로 설정하면 인증서 오류 발생 시에도 요청 진행)
    # connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                response_data = await resp.json()
    except Exception as e:
        print("HTTP 요청 실패:", e)
        await message.channel.send(f"HTTP 요청 실패: {e}")
        return
    print("Spring AI 응답:", response_data)
    # DTO 전체 응답: showMessage가 True이면 메시지 출력
    if response_data.get("showMessage"):
        await message.channel.send(response_data.get("message"))
        DISCORD_CLIENT.CONV_ID = response_data.get("convoId")
