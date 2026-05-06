def build_prompt(
    prompt_id: str,
    prompt_version: str,
    variables: dict | None = None,
) -> dict:
    prompt = {
        "id": prompt_id,
        "version": prompt_version,
    }
    if variables is not None:
        prompt["variables"] = variables
    return prompt


def build_single_image_content(image_url: str | None):
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
