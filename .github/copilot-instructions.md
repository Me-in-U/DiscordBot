# Copilot Instructions for DiscordBot

This repository hosts a modular Discord bot built with `discord.py`. Follow these instructions to understand the architecture, workflows, and conventions.

## Architecture Overview

- **Entry Point**: `bot.py` initializes `commands.Bot`, loads extensions dynamically from `cogs/`, and manages global state (`USER_MESSAGES`, `SETTING_DATA`, `PARTY_LIST`).
- **Cogs System**:
  - **Standard Cogs**: Single `.py` files in `cogs/` (e.g., `music.py`, `summarize.py`).
  - **Package Cogs**: Directories in `cogs/` with `__init__.py` (e.g., `cogs/gambling/`). The `__init__.py` must expose the main Cog class.
- **Voice & AI**:
  - **Voice Chat**: `cogs/voice_chat.py` handles voice processing using `discord.ext.voice_recv` (audio sink), `whisper` (STT), and `pyttsx3` (TTS).
  - **Spring AI**: `func/spring_ai.py` communicates with an external Spring backend for chat capabilities.
  - **YouTube**: `func/youtube_summary.py` and `cogs/music.py` use `yt-dlp` for media handling.

## Data & Configuration

- **Guild Configuration** (`channel_settings.json`):
  - Stores guild-specific channel IDs (e.g., gambling channel, celebration channel).
  - Managed via `util/channel_settings.py`. Always use this utility to read/write channel settings.
- **Feature State** (`settingData.json`):
  - Stores persistent state for specific features like Riot API data (`dailySoloRank`) or YouTube checkers.
  - Path stored in `DISCORD_CLIENT.SETTING_DATA`.
- **Environment**:
  - `.env` file required. Keys: `DISCORD_TOKEN`, `OPENAI_KEY`, `GOOGLE_API_KEY`, `RIOT_KEY`, `SONPANNO_GUILD_ID`.

## Key Components & Patterns

### 1. Gambling System (`cogs/gambling/`)
- Implemented as a **Package Cog**.
- `__init__.py` defines the `GamblingCommands` Cog and imports logic from sub-modules.
- `services.py` (`balance_service`) manages user balances and transactions centrally.
- **Pattern**: Split complex logic into separate files (`blackjack.py`, `slot_machine.py`) but expose commands through the single Cog class in `__init__.py`.

### 2. Voice Processing (`cogs/voice_chat.py`)
- Uses `StreamingSink` class inheriting from `voice_recv.AudioSink`.
- Handles audio buffering, silence detection (VAD), and processing loop.
- **Critical**: Ensure `voice_recv` is available. Handle audio data as PCM bytearrays.

### 3. Global State Management
- `DISCORD_CLIENT.USER_MESSAGES`: Stores recent chat history for context-aware features.
- `DISCORD_CLIENT.PARTY_LIST`: Tracks dynamic voice channels/categories.
- Access global state via `self.bot` in Cogs.

## Developer Workflows

- **Dependency Management**:
  - Use `pip_install.txt` for dependencies.
  - Run: `pip install -r pip_install.txt`
- **Execution (Windows)**:
  - Use `_launchBot.ps1` to activate the virtual environment and run the bot.
  - `_scheduler.ps1` handles auto-updates and restarts.
- **Testing**:
  - Ad-hoc tests in `test/` directory (e.g., `spring_ai_test.py`).
  - No formal unit test suite; rely on manual verification or script execution.

## Coding Conventions

- **Async/Await**:
  - All I/O bound operations (API calls, database, file I/O) must be asynchronous.
  - Use `aiohttp` for HTTP requests (see `func/spring_ai.py`).
- **Path Handling**:
  - Use `pathlib` or `os.path` with `BASE_DIR` (defined in `bot.py` or `util` files) to ensure cross-platform compatibility.
- **Error Handling**:
  - Log errors to console with tracebacks for debugging.
  - Inform users of failures via Discord messages when appropriate.
