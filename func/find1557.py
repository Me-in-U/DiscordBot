import json
import os

from api.chatGPT import structured_response

COUNTER_FILE = "1557Counter.json"


def _load_counts():
    if not os.path.isfile(COUNTER_FILE):
        return {}
    with open(COUNTER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_counts(data):
    with open(COUNTER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


def userCount(author, count):
    """
    OCR 또는 이미지에서 1557이 검출된 작성자의 weeklyCount를 1 증가시킵니다.
    author.id (또는 author.name) 를 키로 사용합니다.
    """
    counts = _load_counts()
    key = str(author.id)  # 또는 author.name
    counts.setdefault(key, 0)
    counts[key] += count
    _save_counts(counts)


def clearCount():
    """
    모든 사용자의 카운트를 0으로 초기화합니다.
    """
    _save_counts({})


async def find1557(message):
    image_url = None

    # 이미지 첨부 확인
    if message.attachments:
        image_url = message.attachments[0].url
    else:
        count = count1557(message.content)
        if count > 0:
            userCount(message.author, count)
            await message.channel.send(f"1557 {count}세트 발견", delete_after=2)
            print(f"1557 발견{count}개")
            return

    # ! 프롬프트 생성
    messages = [
        {
            "role": "developer",
            "content": (
                "사용자 입력 이미지에 대해 다음 조건들이 모두 만족하면 exist에 true, "
                "하나라도 미달이면 exist에 false를 반환해줘.\n\n"
                "조건 1: '1'이라는 숫자(문자)가 최소 1개 이상 존재\n"
                "조건 2: '5'라는 숫자(문자)가 최소 2개 이상 존재\n"
                "조건 3: '7'이라는 숫자(문자)가 최소 1개 이상 존재\n"
                "즉 입력 이미지의 문자로 1557을 구성할 수 있어야한다."
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
    # !image_url이 존재할 때에만 이미지 관련 메시지 추가
    if image_url is not None:
        try:
            response = structured_response(messages)
        except Exception as e:
            print("GPT 호출 중 예외 발생:", e)
            # await message.channel.send("오류가 발생했습니다. 나중에 다시 시도해주세요.")
            return

        print("구조화된 응답:", response)
        # 만약 true라면
        count = count1557(message.content)
        if response.exist and count > 0:
            # 2초 뒤 사라짐
            await message.channel.send(f"1557 {count}세트 발견", delete_after=2)
            userCount(message.author, count)
            print(f"1557 {count}세트 발견")
            return
