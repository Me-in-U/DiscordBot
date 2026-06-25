# https://github.com/openai/openai-python
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI
from util.env_utils import getenv_clean, sanitize_environment

# 환경 변수를 .env 파일에서 로딩
load_dotenv()
sanitize_environment()
OPENAI_KEY = getenv_clean("OPENAI_KEY")

if not OPENAI_KEY:
    raise EnvironmentError("OPENAI_KEY 환경 변수가 설정되지 않았습니다.")

logger = logging.getLogger(__name__)
clientGPT = OpenAI(api_key=OPENAI_KEY)


class OpenAIModelError(Exception):
    """Raised when the OpenAI Responses API call or response parsing fails."""


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
    try:
        if image_content:
            response = clientGPT.responses.create(
                input=image_content,
                prompt=prompt,
            )
        else:
            response = clientGPT.responses.create(
                prompt=prompt,
            )
        logger.debug("OpenAI prompt response received: type=%s", type(response).__name__)
        return _extract_response_text(response)
    except Exception as exc:
        raise OpenAIModelError("OpenAI prompt response failed.") from exc


def generate_text_model(
    user_input: str,
    instructions: str,
    model: str = "gpt-5.4-mini",
    max_output_tokens: int | None = None,
):
    request_kwargs = {
        "model": model,
        "instructions": instructions,
        "input": user_input,
        "reasoning": {"effort": "low"},
        "text": {"verbosity": "low"},
    }
    if max_output_tokens is not None:
        request_kwargs["max_output_tokens"] = max_output_tokens

    try:
        response = clientGPT.responses.create(**request_kwargs)
        logger.debug("OpenAI text response received: type=%s", type(response).__name__)
        return _extract_response_text(response)
    except Exception as exc:
        raise OpenAIModelError("OpenAI text response failed.") from exc
