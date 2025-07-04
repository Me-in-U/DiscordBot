# https://github.com/openai/openai-python
import os

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_KEY")

if not OPENAI_KEY:
    raise EnvironmentError("OPENAI_KEY 환경 변수가 설정되지 않았습니다.")

clientGPT = OpenAI(api_key=OPENAI_KEY)


def general_purpose_model(messages, model="gpt-4.1-mini", temperature=0.5):
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
    return message.strip()


def reasoning_model(messages, model="o4-mini", reasoning_effort="medium"):
    response = clientGPT.chat.completions.create(
        model=model, messages=messages, reasoning_effort=reasoning_effort
    )
    message = response.choices[0].message.content
    return message.strip()


class Exist1557(BaseModel):
    exist: bool
    imageToText: str
    reason: str


def structured_response(messages, model="gpt-4.1-mini", rf=Exist1557):
    try:
        # clientGPT가 올바르게 정의되어 있는지 확인하세요.
        completion = clientGPT.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=rf,
        )
        # print("GPT 응답 전체:", completion)
        parsed = completion.choices[0].message.parsed
        # print("파싱된 응답:", parsed)
        return parsed
    except Exception as e:
        print("structured_response 호출 중 에러 발생:", e)
        raise


def web_search(input: str, model: str = "gpt-4.1-mini") -> str:
    """
    :param input: 검색할 문자열
    :return: 웹 검색 결과를 포함한 모델 응답 텍스트
    """
    response = clientGPT.responses.create(
        model=model,
        tools=[
            {
                "type": "web_search_preview",
                "user_location": {
                    "type": "approximate",
                    "country": "KR",
                    "city": "Seoul",
                    "region": "Seoul",
                },
                "search_context_size": "high",
            }
        ],
        input=input,
    )
    return response.output_text
