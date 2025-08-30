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


def custom_prompt_model(prompt, image_content=None):
    if image_content:
        response = clientGPT.responses.create(
            input=image_content,
            prompt=prompt,
        )
    else:
        response = clientGPT.responses.create(
            prompt=prompt,
        )
    print(response)
    try:
        message = response.output_text
    except AttributeError:
        message = ""
        for item in response.output:
            if getattr(item, "type", None) == "message":
                for c in item.content:
                    if getattr(c, "type", None) == "output_text":
                        message += c.text
    return message.strip()
