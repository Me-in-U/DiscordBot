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
  - `.env` file required. Keys include `DISCORD_TOKEN`, `OPENAI_KEY`, `GOOGLE_API_KEY`, `RIOT_KEY`, `SONPANNO_GUILD_ID`, `SSAFY_GUILD_ID`, `DB_HOST`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD`, `API_PORT`, `CELEBRATION_UPDATE_API_KEY`, and `ECOS_API_KEY`.
  - Keep local runtime values in `.env` and deployment runtime values in `.env.deploy`; both files are local secrets and must stay out of Git.
  - In deployment, `DB_HOST` must point to the Docker host gateway, for example `host.docker.internal:3306`, because the shared MySQL service binds to the host loopback port and is reached from the bot container through Docker's host gateway.
  - YouTube live notifications use WebSub. Set `YOUTUBE_WEBSUB_CALLBACK_URL` to the public HTTPS callback ending in `/youtube/websub`, and set `YOUTUBE_WEBSUB_VERIFY_TOKEN` to a long random token.

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
  - Ad-hoc tests in `test/` directory (e.g., `spring_ai_test.py`).
  - No formal unit test suite; rely on manual verification or script execution.

## Deployment Ownership

- This public repository owns only the bot application, its Docker assets, the example `Jenkinsfile`, and `scripts/jenkins_deploy.sh`.
- Shared Jenkins controller, inbound agents, and n8n runtime are managed in an external/private environment and are not defined in this repository.
- Keep committed docs generic: do not mention private repository names, local absolute paths, internal webhook URLs, or other internal operations details.
- The example `Jenkinsfile` uses the label `discordbot-docker`; self-hosters may rename it if they also update the pipeline accordingly.
- Jenkins deploys restore the root `.env.deploy` file from the Secret text credential `discordbot-env`, referenced by `Jenkinsfile` as `ENV_CREDENTIAL_ID`.
- When server deployment values in `.env.deploy` change, update the Jenkins `discordbot-env` credential in the same work session; a repo diff alone does not change the deployed environment.
- Preferred credential update method: replace the entire Secret text payload with the current root `.env.deploy` content via Jenkins Credentials UI or Script Console, then verify the stored credential matches the local file content before ending the task.
- Script Console fallback procedure: if the browser credential form fails with `400 This page expects a form submission` or `No valid crumb was included`, fetch a fresh Jenkins crumb and authenticated session cookie first, then post to `/scriptText` and replace the full `discordbot-env` Secret text payload with the current `.env.deploy` content in one shot.
- Verification procedure: after updating the credential, re-read `discordbot-env` through Jenkins Script Console and compare a SHA-256 hash of the stored payload against the local `.env.deploy` file; if hashing is inconvenient, at least verify the changed key lines match exactly before ending the task.

## Coding Conventions

- **Async/Await**:
  - All I/O bound operations (API calls, database, file I/O) must be asynchronous.
  - Use `aiohttp` for HTTP requests (see `func/spring_ai.py`).
- **Path Handling**:
  - Use `pathlib` or `os.path` with `BASE_DIR` (defined in `bot.py` or `util` files) to ensure cross-platform compatibility.
- **Error Handling**:
  - Log errors to console with tracebacks for debugging.
  - Inform users of failures via Discord messages when appropriate.
