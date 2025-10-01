# Copilot instructions for this repo (DiscordBot)

This Python Discord bot is modular (Cogs) and Windows-oriented. Use these notes to be productive fast.

## Architecture at a glance

- Entry: `bot.py`
  - Creates `DISCORD_CLIENT` (discord.py), loads every module in `cogs/` via `load_extension`.
  - Global state on client: `USER_MESSAGES` (per-guild per-user message timeline), Spring AI flags (mode/style/convoIds), `SETTING_DATA` path, `PARTY_LIST`.
  - Event flow in `on_message`: store message -> `check_youtube_link()` (YouTube summary prompt UI) -> `find1557()` (pattern/count + OCR) -> `spring_ai()` (if AI mode).
  - Startup syncs slash commands globally: `DISCORD_CLIENT.tree.sync()`.
- Background loops: `cogs/loop.py`
  - Presence updates, midnight reset + holidays/special-days notice, weekly 1557 report, optional YouTube live checker.
  - Uses `settingData.json` and `special_days.json`.
- Features by Cog (examples):
  - `cogs/summarize.py` and `util/get_recent_messages.py` format today’s chat for GPT.
  - `cogs/translation.py` shows dropdown-then-edit flow with optional image input to GPT.
  - `cogs/spring_ai.py` toggles Spring AI mode/style; responses handled by `func/spring_ai.py` (remote API, per-style convoId persistence).
  - `cogs/YoutubeCheckerCog.py` toggles live-check loop by mutating `settingData.json`.
- External wrappers / utils: `api/chatGPT.py` (OpenAI Responses API), `api/riot.py`, `func/youtube_summary.py` (yt-dlp/FFmpeg/Google API, comments + transcript + Whisper fallback), `func/find1557.py` (pattern/OCR with GPT).

## Run, env, and dependencies

- Environment (.env) required:
  - `DISCORD_TOKEN`, `MY_CHANNEL_ID`, `TEST_CHANNEL_ID`, `GUILD_ID`
  - `OPENAI_KEY`, `GOOGLE_API_KEY`, `RIOT_KEY`
- Install deps (note: requirements.txt not present; use this file): `pip_install.txt`.
- Windows launch scripts:
  - Dev: `._launchBot.ps1` or `._launchBot.bat` (activates `.venv`, runs `python bot.py`).
  - Auto-update runner: `._scheduler.ps1` -> runs `_autoPullAndLaunch.py` (git stash+pull; restarts launch script if changes).
- Media tools: put `bin/ffmpeg.exe` to prefer local FFmpeg; optional `cookies.txt` improves yt-dlp reliability.

## Patterns and conventions

- Cogs auto-load if placed in `cogs/` and expose `async def setup(bot): await bot.add_cog(...)`.
- Slash commands use `discord.app_commands` (see `cogs/custom_help.py`, `cogs/translation.py`). Startup does a global sync.
- Message history is “today-only”: `load_recent_messages()` scans each text channel (limit=100) for today and normalizes to `USER_MESSAGES`. Daily reset occurs at midnight in `LoopTasks.new_day_clear`.
- OpenAI usage: call `api.chatGPT.custom_prompt_model(prompt={id, version, variables}, image_content=...)`. The code expects remote prompt IDs; follow the existing call sites to add variables.
- YouTube summary flow (`func/youtube_summary.py`):

1.  Button prompt on link -> 2) try transcript (ko→en→auto) with yt-dlp → 3) fallback MP3+Whisper → 4) GPT summary → 5) append comments summary via YouTube Data API.
    Live/Upcoming videos are skipped.

## Extending the bot

- New feature = new Cog in `cogs/`.
  - For scheduled jobs, use `discord.ext.tasks` like `LoopTasks`; guard with config flags in `settingData.json` if user-togglable.
  - To use chat context, import `util.get_recent_messages` or read `DISCORD_CLIENT.USER_MESSAGES[guild_id]`.
- External APIs:
  - Riot: use `api.riot.get_rank_data(game_name, tag_line, rank_type)`.
  - Spring AI: `func.spring_ai.spring_ai(DISCORD_CLIENT, message)` is auto-called in `on_message` when AI mode is on; just manage toggles in your Cog.

## Gotchas

- Don’t add requirements to README; install from `pip_install.txt` (current source of truth).
- Slash command not visible? Wait for global sync or restart bot.
- YouTube/Whisper are CPU/network heavy; tests under `test/` are ad-hoc scripts, not pytest suites.
- Summaries/translation operate on today’s messages only unless you expand `load_recent_messages()`.

If any of these are unclear (e.g., prompt IDs for GPT, expected variables, or how to add a new loop with config), tell me what you’re building and I’ll refine these rules.
