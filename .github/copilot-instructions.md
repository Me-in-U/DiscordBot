# Copilot guide for DiscordBot

This repo hosts a modular Discord bot built with `discord.py`. Use these pointers to hit the ground running.

## Architecture snapshot

- **Entry point**: `bot.py` initializes `commands.Bot`, loads extensions from `cogs/`, and manages global state (`USER_MESSAGES`, `SETTING_DATA`, `PARTY_LIST`).
- **Cogs System**:
  - **Standard Cogs**: Single `.py` files in `cogs/` (e.g., `music.py`, `summarize.py`).
  - **Package Cogs**: Directories in `cogs/` with `__init__.py` (e.g., `cogs/gambling/`). The `__init__.py` aggregates logic from sub-modules into a single Cog class.
- **Message Flow**: `on_message` in `bot.py` logs messages -> `func.youtube_summary` (summary button) -> `func.find1557` (meme detection) -> `func.spring_ai` (auto-reply).
- **Background Tasks**: `cogs/loop.py` handles scheduled tasks (midnight reset, presence ticker, holiday announcements).

## Key Components & Patterns

- **Gambling System** (`cogs/gambling/`):
  - Implemented as a package. `__init__.py` defines the `GamblingCommands` Cog.
  - Logic is split across files (`blackjack.py`, `slot_machine.py`) but exposed via the single Cog.
  - Uses `services.py` for shared state/logic.
- **Music System** (`cogs/music.py`):
  - Monolithic Cog handling playback, queue, and UI panels.
  - Uses `yt-dlp` for media extraction and `ffmpeg` for playback.
- **AI Integration**:
  - **Spring AI**: Toggles via `/ai`. Logic in `func/spring_ai.py` maintains conversation context per style.
  - **YouTube Summary**: `func/youtube_summary.py` combines `yt-dlp` (audio), Whisper (STT), and GPT (summary).
- **Global State**:
  - `DISCORD_CLIENT.USER_MESSAGES`: Stores recent chat history (limit 100/channel) for context-aware AI features.
  - `DISCORD_CLIENT.SETTING_DATA`: Path to `settingData.json` for persistent config.

## Setup & Workflows

- **Environment**:
  - Keys in `.env`: `DISCORD_TOKEN`, `OPENAI_KEY`, `GOOGLE_API_KEY`, `RIOT_KEY`, `SONPANNO_GUILD_ID`.
  - **Dependencies**: Use `pip_install.txt`, NOT `requirements.txt`.
- **Execution (Windows)**:
  - `_launchBot.ps1`: Activates venv and runs `bot.py`.
  - `_scheduler.ps1` -> `_autoPullAndLaunch.py`: Auto-update loop (git pull + restart).
- **Testing**:
  - No formal test suite. Ad-hoc scripts in `test/` (e.g., `spring_ai_test.py`).
  - Run tests manually: `python test/spring_ai_test.py`.

## Development Guidelines

- **Adding Commands**:
  - Use `discord.app_commands` for slash commands.
  - For new features, prefer creating a new Cog in `cogs/`.
  - If complex, create a package in `cogs/` (like `gambling`).
- **Data Persistence**:
  - Use `settingData.json` for guild-specific settings (channel IDs, toggles).
  - Use `util/channel_settings.py` helpers to read/write settings.
- **Async/Sync**:
  - Heavy operations (YouTube download, OpenAI calls) must not block the event loop.
  - Ensure `await` is used for I/O bound tasks.

## Common Files

- `bot.py`: Main entry, Cog loader.
- `cogs/loop.py`: Scheduled tasks.
- `pip_install.txt`: Dependency list.
- `settingData.json`: Configuration storage.
