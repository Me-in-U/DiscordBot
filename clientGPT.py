import os

from dotenv import load_dotenv
from openai import OpenAI

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_KEY")

clientGPT = OpenAI(api_key=OPENAI_KEY)


def send_to_chatgpt(messages, model="gpt-4o-mini-2024-07-18", temperature=0.5):
    response = clientGPT.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=500,
        temperature=temperature,
    )
    message = response.choices[0].message.content
    print(message)
    messages.append(response.choices[0].message)
    return message
