import aiohttp


async def spring_ai(DISCORD_CLIENT, message):
    # ! AI모드가 활성화되어 있고, 봇이 보낸 메시지가 아니면 처리
    if not DISCORD_CLIENT.SPRING_AI_MODE or message.author == DISCORD_CLIENT.user:
        return
    if DISCORD_CLIENT.SPRING_AI_STYLE == "공격적":
        endpoint = "aggressive"
        conv_attr = "CONV_ID_AGGRESSIVE"
    else:
        endpoint = "friendly"
        conv_attr = "CONV_ID_FRIENDLY"

    url = f"https://api.sonpanno.com/api/v1/discord/chat/{endpoint}"
    # url = f"http://localhost:8080/api/v1/discord/chat/{endpoint}"
    currentConvId = getattr(DISCORD_CLIENT, conv_attr, None)
    payload = {
        "message": f"{message.content}",
        "convoId": currentConvId,
    }

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
        # 응답에 새로운 convoId가 있으면 업데이트
        new_conv = response_data.get("convoId")
        if new_conv:
            setattr(DISCORD_CLIENT, conv_attr, new_conv)
