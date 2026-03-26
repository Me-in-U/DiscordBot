from pathlib import Path

from util.env_utils import getenv_clean


def get_data_dir() -> Path:
    data_dir = Path(getenv_clean("BOT_DATA_DIR", "/app/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def data_file_path(filename: str) -> str:
    return str(get_data_dir() / filename)
