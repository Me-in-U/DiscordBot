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


def check1557(ocr_text: str) -> bool:
    """
    OCR 문자열에서 '1', '5', '7'이 조건에 맞게 존재하는지 확인한다.
    조건 1: '1' >= 1개
    조건 2: '5' >= 2개
    조건 3: '7' >= 1개
    """
    count_1 = ocr_text.count("1")
    count_5 = ocr_text.count("5")
    count_7 = ocr_text.count("7")
    return (count_1 >= 1) and (count_5 >= 2) and (count_7 >= 1)


def userCount(author):
    """
    OCR 또는 이미지에서 1557이 검출된 작성자의 weeklyCount를 1 증가시킵니다.
    author.id (또는 author.name) 를 키로 사용합니다.
    """
    counts = _load_counts()
    key = str(author.id)  # 또는 author.name
    counts.setdefault(key, 0)
    counts[key] += 1
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
        if check1557(message.content):
            userCount(message.author)
            print("1557 발견")
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
        if response.exist or check1557(response.imageToText):
            await message.channel.send("1557")
            userCount(message.author)
            print("1557 발견")
            return
