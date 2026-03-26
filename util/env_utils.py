import os


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def sanitize_environment() -> None:
    for key, value in list(os.environ.items()):
        cleaned = _clean_value(value)
        if cleaned != value:
            os.environ[key] = cleaned


def getenv_clean(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key, default)
    return _clean_value(value)
