# syntax=docker/dockerfile:1.7

ARG DEPS_IMAGE=bot-discord-bot-deps:latest
FROM ${DEPS_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY . /app

CMD ["python", "bot.py"]
