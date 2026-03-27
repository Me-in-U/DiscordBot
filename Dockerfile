FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

CMD ["python", "bot.py"]
