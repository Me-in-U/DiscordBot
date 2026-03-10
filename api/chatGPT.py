# https://github.com/openai/openai-python
import os

from dotenv import load_dotenv
from openai import OpenAI

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_KEY")

if not OPENAI_KEY:
    raise EnvironmentError("OPENAI_KEY 환경 변수가 설정되지 않았습니다.")

clientGPT = OpenAI(api_key=OPENAI_KEY)


def _extract_response_text(response) -> str:
    try:
        message = response.output_text
    except AttributeError:
        message = ""
        for item in response.output:
            if getattr(item, "type", None) == "message":
                for content in item.content:
                    if getattr(content, "type", None) == "output_text":
                        message += content.text
    return message.strip()


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
    return _extract_response_text(response)


def generate_text_model(
    user_input: str,
    instructions: str,
    model: str = "gpt-5-mini",
    max_output_tokens: int | None = None,
):
    request_kwargs = {
        "model": model,
        "instructions": instructions,
        "input": user_input,
        "reasoning": {"effort": "minimal"},
        "text": {"verbosity": "low"},
    }
    if max_output_tokens is not None:
        request_kwargs["max_output_tokens"] = max_output_tokens

    response = clientGPT.responses.create(**request_kwargs)
    print(response)
    return _extract_response_text(response)
