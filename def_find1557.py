import json
from requests_gpt import structured_response


async def find1557(message):
    image_url = None

    # 이미지 첨부 확인
    if message.attachments:
        image_url = message.attachments[0].url

    messages = [
        {
            "role": "developer",
            "content": "유저의 채팅내용 혹은 사진이 입력된다. 입력된 내용 중 다음 3개의 조건이 모두 만족 하면 true를 아니면 false를 반환해라. 조건 1 : 숫자1이 1개이상 존재, 조건 2 : 숫자5가 2개이상 존재, 조건 3 : 숫자7이 1개 이상 존재",
        },
        {
            "role": "user",
            "content": f"{message.content}",
        },
    ]
    # image_url이 존재할 때에만 이미지 관련 메시지 추가
    if image_url is not None:
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                            },
                        },
                    ]
                ),
            }
        )
    # print("GPT에게 보낼 메시지:", messages)
    try:
        response = structured_response(messages)
    except Exception as e:
        print("GPT 호출 중 예외 발생:", e)
        # 에러 상황에서는 후속 처리를 할 수 있음 (예: 디폴트 메시지 전송)
        # await message.channel.send("오류가 발생했습니다. 나중에 다시 시도해주세요.")
        return

    # print("구조화된 응답:", response)
    # 만약 true라면
    if response.exist:
        await message.channel.send("1557")
