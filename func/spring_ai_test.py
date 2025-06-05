import aiohttp

CONV_ID = None
message = type("Message", (object,), {"content": "손성락 KR2 솔랭 알려줘"})


async def spring_ai():
    url = "https://api.sonpanno.com/api/v1/discord/chat"
    url = "http://localhost:8080/api/v1/discord/chat"
    payload = {
        "message": message.content,
        "convoId": CONV_ID,
    }
    # SSL 검증을 끄는 컨텍터 생성 (False로 설정하면 인증서 오류 발생 시에도 요청 진행)
    # connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                response_data = await resp.json()
    except Exception as e:
        print("HTTP 요청 실패:", e)
        return
    print("Spring AI 응답:", response_data)


# 실행
if __name__ == "__main__":
    import asyncio

    asyncio.run(spring_ai())
