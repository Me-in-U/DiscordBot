# Copilot guide for DiscordBot

This repo hosts a modular Discord bot built with `discord.py`. Use these pointers to hit the ground running.

## Architecture snapshot

- Entry point: `bot.py` boots `commands.Bot`, loads every module under `cogs/`, and wires global state (`USER_MESSAGES`, Spring AI flags, `SETTING_DATA`, `PARTY_LIST`).
- Message flow (`on_message` in `bot.py`): log message ➜ `func.youtube_summary.check_youtube_link` (offer summary button) ➜ `func.find1557.find1557` (detect “1557” text/image hits via GPT OCR) ➜ `func.spring_ai.spring_ai` (auto-reply when Spring AI mode on).
- Background tasks live in `cogs/loop.py`: presence ticker, midnight reset + holiday/special-day announcements, weekly 1557 report, optional YouTube live checker driven by `settingData.json`.
- Key Cogs (examples):
  - `cogs/summarize.py` + `util/get_recent_messages.py` send today’s chat (limit 150) to GPT.
  - `cogs/translation.py` showcases dropdown-driven translation with optional image attachments.
  - `cogs/spring_ai.py` toggles Spring AI mode/style; the API bridge sits in `func/spring_ai.py` (per-style convoId persistence).
  - `cogs/YoutubeCheckerCog.py` exposes a slash command to flip the live-check loop flag inside `settingData.json`.
- External wrappers: `api/chatGPT.py` (OpenAI Responses API via prompt IDs), `api/riot.py` (Riot rank lookups), large `func/youtube_summary.py` (yt-dlp/FFmpeg download, Whisper STT fallback, GPT summary, YouTube comment summarization).

## Setup & workflows

- Required `.env` keys: `DISCORD_TOKEN`, `MY_CHANNEL_ID`, `TEST_CHANNEL_ID`, `GUILD_ID`, `OPENAI_KEY`, `GOOGLE_API_KEY`, `RIOT_KEY`.
- Dependencies: install from `pip_install.txt` (no `requirements.txt`).
- Windows launch scripts:
  - `_launchBot.ps1` / `_launchBot.bat`: activate `.venv` then run `python bot.py`.
  - `_scheduler.ps1` ➜ `_autoPullAndLaunch.py`: cron-style loop doing `git stash/pull` and restarting `_launchBot.ps1` when updates arrive.
- For media features, place `ffmpeg.exe` under `bin/`. Optional `cookies.txt` boosts yt-dlp reliability.

## Conventions & extension tips

- Cogs auto-load if they live in `cogs/` and expose `async def setup(bot): await bot.add_cog(...)`.
- Slash commands use `discord.app_commands`; `bot.py` performs a global sync on startup (expect propagation delay).
- Chat context is “today-only”: `load_recent_messages()` scans each guild channel (limit 100) and stores normalized entries in `USER_MESSAGES`; `LoopTasks.new_day_clear` resets nightly.
- OpenAI usage pattern: call `custom_prompt_model(prompt={"id": ..., "version": ..., "variables": {...}}, image_content=...)`. Reuse prompt IDs already embedded in the repo unless product requirements change.
- YouTube summary flow (`func/youtube_summary.py`):
  1. Button UI asks for confirmation.
  2. Try localized subtitles (ko → en → auto); fallback to MP3 download + Whisper transcription.
  3. Send summary prompt and append comment digest via YouTube Data API.
  4. Skip live/upcoming streams (`is_live_video`).
- Spring AI auto-reply triggers only when `SPRING_AI_MODE` is true; toggled via `/ai` and `/ai성격`. Conversation IDs persist per tone.

## What to watch for

- Missing deps? cross-check `pip_install.txt` before editing README.
- Slash command not visible immediately: global sync can take minutes; restart if schema changed.
- Heavy jobs (YouTube, Whisper) are synchronous from the command handler—expect blocking if run often.
- Tests under `test/` are ad-hoc scripts (e.g., `spring_ai_test.py`); there’s no pytest harness—run them manually if needed.

Unclear about prompt variables, new Cog scaffolding, or scheduled task patterns? Ask for specifics so we can extend these rules.
