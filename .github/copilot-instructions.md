# Copilot Instructions for DiscordBot

This repository hosts a modular Discord bot built with `discord.py`. Follow these instructions to understand the architecture, workflows, and conventions.

## Architecture Overview

- **Entry Point**: `bot.py` initializes `commands.Bot`, loads extensions dynamically from `cogs/`, and manages global state (`USER_MESSAGES`, `PARTY_LIST`).
- **Cogs System**:
  - **Standard Cogs**: Single `.py` files in `cogs/` (e.g., `music.py`, `summarize.py`).
  - **Package Cogs**: Directories in `cogs/` with `__init__.py` (e.g., `cogs/gambling/`). The `__init__.py` must expose the main Cog class.
- **Voice & AI**:
  - **Voice Chat**: `cogs/voice_chat.py` handles voice processing using `discord.ext.voice_recv` (audio sink), `whisper` (STT), and `pyttsx3` (TTS).
  - **Spring AI**: `func/spring_ai.py` communicates with an external Spring backend for chat capabilities.
  - **YouTube**: `func/youtube_summary.py` and `cogs/music.py` use `yt-dlp` for media handling.

## Data & Configuration

- **Guild Configuration** (`channel_settings` table):
  - Stores guild-specific channel IDs (e.g., gambling channel, celebration channel).
  - Managed via `util/channel_settings.py`. Always use this utility to read/write channel settings.
- **Feature State** (`setting_data` table):
  - Stores persistent state for specific features like Riot API data (`dailySoloRank`) or YouTube checkers.
  - Access through DB helpers in `util/db.py`, not local JSON files.
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
  - If PowerShell is inconvenient, `_launchBot.bat` provides the same local entry point.
- **Testing**:
  - Use Python 3.11 for Docker/runtime parity. When verification is requested, run `python -m compileall -q bot.py api cogs common func util test` and `python -m unittest discover -s test`.
  - Focused tests also use discovery, for example `python -m unittest discover -s test -p "test_tibo_daily_log.py"`; `test/` is not an importable package.
  - Choose mocks by the call expression. For `async with session.get(url)`, use an explicit `MagicMock` session and request context manager; use `AsyncMock` for context entry/exit and awaited response methods. Do not take the default `ClientSession.__aenter__.return_value` as the session without configuring it.
  - Reuse `test/test_codex_resets_fetcher.py` and `test/test_tibo_daily_log.py`. Read [the incident analysis and test pattern](../docs/async-http-testing.md) before adding aiohttp tests.
  - Honor the user's validation scope and distinguish tests written, tests run, Git push, Jenkins verification, and deployment success.
  - Capture intentional failure logs with `assertLogs` while asserting the fallback or cleanup outcome; preserve production error logging. See [Jenkins log analysis](../docs/jenkins-log-analysis-2026-10-11.md).

## Deployment Ownership

- This public repository owns only the bot application, its Docker assets, the example `Jenkinsfile`, and `scripts/jenkins_deploy.sh`.
- Shared Jenkins controller, inbound agents, and n8n runtime are managed in an external/private environment and are not defined in this repository.
- Keep committed docs generic: do not mention private repository names, local absolute paths, internal webhook URLs, or other internal operations details.
- The example `Jenkinsfile` uses the label `discordbot-docker`; self-hosters may rename it if they also update the pipeline accordingly.

## Coding Conventions

- **Async/Await**:
  - All I/O bound operations (API calls, database, file I/O) must be asynchronous.
  - Use `aiohttp` for HTTP requests (see `func/spring_ai.py`).
- **Path Handling**:
  - Use `pathlib` or `os.path` with `BASE_DIR` (defined in `bot.py` or `util` files) to ensure cross-platform compatibility.
- **Error Handling**:
  - Log errors to console with tracebacks for debugging.
  - Inform users of failures via Discord messages when appropriate.
