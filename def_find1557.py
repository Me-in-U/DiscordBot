import json
from requests_gpt import structured_response


def check_1557_condition(ocr_text: str) -> bool:
    """
    OCR 문자열(ocr_text)에서 '1', '5', '7'이 조건에 맞게 존재하는지 확인한다.
    조건 1: '1' >= 1개
    조건 2: '5' >= 2개
    조건 3: '7' >= 1개
    """
    count_1 = ocr_text.count("1")
    count_5 = ocr_text.count("5")
    count_7 = ocr_text.count("7")
    # print("1개수 : ", count_1)
    # print("5개수 : ", count_5)
    # print("7개수 : ", count_7)
    return (count_1 >= 1) and (count_5 >= 2) and (count_7 >= 1)


async def find1557(message):
    image_url = None

    # 이미지 첨부 확인
    if message.attachments:
        image_url = message.attachments[0].url
    else:
        if check_1557_condition(message.content):
            await message.channel.send("1557")
            return

    messages = [
        {
            "role": "developer",
            "content": (
                "사용자 입력 이미지에 대해 다음 조건들이 모두 만족하면 exist에 true, "
                "하나라도 미달이면 exist에 false를 반환해줘.\n\n"
                "조건 1: '1'이라는 숫자(문자)가 최소 1개 이상 존재\n"
                "조건 2: '5'라는 숫자(문자)가 최소 2개 이상 존재\n"
                "조건 3: '7'이라는 숫자(문자)가 최소 1개 이상 존재\n"
            ),
        },
        {
            "role": "developer",
            "content": (
                "조건 요약:\n"
                "1. 최소 1개의 '1'\n"
                "2. 최소 2개의 '5'\n"
                "3. 최소 1개의 '7'\n"
            ),
        },
        {
            "role": "developer",
            "content": "이미지의 모든 문자를 imageToText에 넣어서 반환해라",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url,
                    },
                }
            ],
        },
    ]
    # image_url이 존재할 때에만 이미지 관련 메시지 추가
    if image_url is not None:
        try:
            response = structured_response(messages)
        except Exception as e:
            print("GPT 호출 중 예외 발생:", e)
            # await message.channel.send("오류가 발생했습니다. 나중에 다시 시도해주세요.")
            return

        print("구조화된 응답:", response)
        # 만약 true라면
        if response.exist or check_1557_condition(response.imageToText):
            await message.channel.send("1557")
            return
