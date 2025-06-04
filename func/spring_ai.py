import aiohttp


async def spring_ai(DISCORD_CLIENT, message):
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
