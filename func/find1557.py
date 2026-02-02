import json
import os
from api.chatGPT import custom_prompt_model
from util.db import execute_query


def count1557(ocr_text: str) -> int:
    """
    OCR 문자열에서 '1', '5', '7'이 조건에 맞게 존재하는지 확인한다.
    조건 1: '1' >= 1개
    조건 2: '5' >= 2개
    조건 3: '7' >= 1개
    """
    count_1 = ocr_text.count("1")
    count_5 = ocr_text.count("5") // 2
    count_7 = ocr_text.count("7")
    if count_1 > 0 and count_5 > 0 and count_7 > 0:
        return min(count_1, count_5, count_7)
    return 0


async def userCount(author, count):
    """
    OCR 또는 이미지에서 1557이 검출된 작성자의 weeklyCount를 1 증가시킵니다.
    author.id (또는 author.name) 를 키로 사용합니다.
    """
    key = int(author.id)
    query = """
    INSERT INTO counter_1557 (user_id, count) VALUES (%s, %s)
    ON DUPLICATE KEY UPDATE count = count + %s
    """
    await execute_query(query, (key, count, count))


async def clearCount():
    """
    모든 사용자의 카운트를 0으로 초기화합니다.
    """
    await execute_query("DELETE FROM counter_1557")


async def find1557(message):
    image_url = None

    # !이미지 첨부 확인
    if message.attachments:
        image_url = message.attachments[0].url
    else:
        count = count1557(message.content)
        if count > 0:
            await userCount(message.author, count)
            await message.channel.send(f"1557 {count}세트 발견", delete_after=2)
            print(f"1557 발견{count}개")
            return

    # !image_url이 존재할 때에만 이미지 관련 메시지 추가
    if image_url is not None:
        image_content = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": image_url,
                    }
                ],
            },
        ]
        try:
            response = custom_prompt_model(
                image_content=image_content,
                prompt={
                    "id": "pmpt_68ad1661f57c8190b18ab6adfaa69c4d0c4d98e2fa43e7fa",
                    "version": "5",
                },
            )
        except Exception as e:
            print("GPT 호출 중 예외 발생:", e)
            # await message.channel.send("오류가 발생했습니다. 나중에 다시 시도해주세요.")
            return
        response = json.loads(response)
        print("구조화된 응답:", response)
        # 만약 true라면
        if response["exist"]:
            count = count1557(response["imageToText"])
            if count:
                await message.channel.send(f"1557 {count}세트 발견", delete_after=2)
                await userCount(message.author, count)
                print(f"1557 {count}세트 발견")
                return
