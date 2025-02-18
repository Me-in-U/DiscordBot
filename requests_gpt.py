import os

from dotenv import load_dotenv
from openai import OpenAI

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_KEY")

if not OPENAI_KEY:
    raise EnvironmentError("OPENAI_KEY 환경 변수가 설정되지 않았습니다.")

clientGPT = OpenAI(api_key=OPENAI_KEY)


def send_to_chatgpt(messages, model="gpt-4o", temperature=0.5):
    """
    OpenAI ChatGPT API를 호출하여 응답을 반환합니다.

    :param messages: 대화 형식의 메시지 리스트. 각 항목은 {"role": "user|assistant|developer", "content": "내용"} 형식.
    :param model: 사용할 모델 이름. 기본값은 "gpt-4".
    :param temperature: 생성의 무작위성 제어 (0.0~1.0). 기본값은 0.5.
    :param max_tokens: 출력 최대 토큰 수. 기본값은 500.
    :return: ChatGPT 응답 메시지 (str).
    """
    response = clientGPT.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    message = response.choices[0].message.content
    print(message)
    messages.append(response.choices[0].message)
    return message


def image_analysis(messages, model="gpt-4o", image_url="", temperature=0.5):
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "이미지가 있습니다. 이미지 내용을 확인하세요",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url,
                    },
                },
            ],
        },
    )
    response = clientGPT.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    message = response.choices[0].message.content
    messages.append(response.choices[0].message)
    return message.strip()
