from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeAlias


PromptPayload: TypeAlias = dict[str, Any]
OpenAIInputContent: TypeAlias = list[dict[str, Any]]
LabeledImageInput: TypeAlias = tuple[str, str]


def build_prompt(
    prompt_id: str,
    prompt_version: str,
    variables: dict[str, Any] | None = None,
) -> PromptPayload:
    prompt = {
        "id": prompt_id,
        "version": prompt_version,
    }
    if variables is not None:
        prompt["variables"] = variables
    return prompt


def build_single_image_content(image_url: str | None) -> OpenAIInputContent | None:
    if not image_url:
        return None

    return [
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


def build_labeled_image_content(
    images: Iterable[LabeledImageInput],
) -> OpenAIInputContent | None:
    content = []
    for label, image_url in images:
        normalized_url = str(image_url or "").strip()
        if not normalized_url:
            continue

        normalized_label = str(label or "").strip()
        if normalized_label:
            content.append(
                {
                    "type": "input_text",
                    "text": normalized_label,
                }
            )
        content.append(
            {
                "type": "input_image",
                "image_url": normalized_url,
            }
        )

    if not content:
        return None

    return [
        {
            "role": "user",
            "content": content,
        }
    ]
