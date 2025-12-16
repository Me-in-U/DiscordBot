import asyncio
import os
import tempfile
import wave
import discord
import traceback
import time
import numpy as np
from discord.ext import commands
from discord import app_commands
import whisper
import pyttsx3

# Try to import voice_recv, if not available, we can't do voice receive
try:
    from discord.ext import voice_recv
except ImportError:
    voice_recv = None


class StreamingSink(voice_recv.AudioSink if voice_recv else object):
    def __init__(self, cog, command_user, vc):
        self.cog = cog
        self.command_user = command_user
        self.vc = vc
        self.user_buffers = {}  # user -> bytearray
        self.user_silence_start = {}  # user -> timestamp
        self.user_speaking = {}  # user -> bool

        # VAD Constants
        self.SILENCE_THRESHOLD = 1000  # Increased from 500 to reduce noise sensitivity
        self.SILENCE_DURATION = 3.0  # Seconds of silence to trigger processing
        self.MIN_SPEECH_DURATION = 1.0  # Increased from 0.5 to avoid short noises

    def wants_opus(self):
        return False

    def write(self, user, data):
        # Calculate RMS
        pcm_data = np.frombuffer(data.pcm, dtype=np.int16).astype(np.float32)
        rms = np.sqrt(np.mean(pcm_data**2))
        now = time.time()

        if user not in self.user_buffers:
            self.user_buffers[user] = bytearray()
            self.user_speaking[user] = False
            self.user_silence_start[user] = now

        # VAD Logic
        if rms > self.SILENCE_THRESHOLD:
            self.user_speaking[user] = True
            self.user_silence_start[user] = now
            self.user_buffers[user].extend(data.pcm)
        else:
            # Silence
            if self.user_speaking[user]:
                # Was speaking, now silent. Keep recording for a bit (buffer silence)
                self.user_buffers[user].extend(data.pcm)

                if now - self.user_silence_start[user] > self.SILENCE_DURATION:
                    # Silence exceeded threshold -> End of sentence
                    self.flush_user(user)
            else:
                # Was silent, still silent. Do nothing (or keep small buffer for context?)
                # For simplicity, we ignore pure silence
                pass

    def flush_user(self, user):
        buffer = self.user_buffers[user]
        duration = len(buffer) / (48000 * 2 * 2)  # 48k, stereo, 16bit

        if duration >= self.MIN_SPEECH_DURATION:
            # Save to file
            f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            f.close()

            with wave.open(f.name, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(48000)
                wf.writeframes(buffer)

            print(f"[DEBUG] VAD triggered for {user.name}. Duration: {duration:.2f}s")

            # Trigger processing
            asyncio.run_coroutine_threadsafe(
                self.cog.process_audio(f.name, user, self.command_user, self.vc),
                self.cog.bot.loop,
            )

        # Reset state
        self.user_buffers[user] = bytearray()
        self.user_speaking[user] = False

    def cleanup(self):
        pass


class VoiceChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.model = None
        self.active_chats = {}  # user_id -> task
        self.transcribe_lock = asyncio.Lock()

    async def load_model(self):
        # Ensure ffmpeg is in PATH
        ffmpeg_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "bin")
        )
        if ffmpeg_path not in os.environ["PATH"]:
            os.environ["PATH"] += os.pathsep + ffmpeg_path

        # Check if ffmpeg is actually callable
        import shutil

        if shutil.which("ffmpeg") is None:
            print(f"Warning: ffmpeg not found in PATH. Added path: {ffmpeg_path}")
            if not os.path.exists(os.path.join(ffmpeg_path, "ffmpeg.exe")):
                print(f"Error: ffmpeg.exe not found in {ffmpeg_path}")

        if self.model is None:
            print("Loading Whisper model...")
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                None, lambda: whisper.load_model("small").to("cpu")
            )
            print("Whisper model loaded.")

    @app_commands.command(
        name="창섭이랑대화",
        description="음성 채널에 봇을 초대하여 실시간 대화를 시작합니다.",
    )
    async def start_chat(self, interaction: discord.Interaction):
        if voice_recv is None:
            await interaction.response.send_message(
                "discord-ext-voice-recv 모듈이 설치되지 않았습니다.", ephemeral=True
            )
            return

        if not interaction.user.voice:
            await interaction.response.send_message(
                "음성 채널에 먼저 입장해주세요.", ephemeral=True
            )
            return

        channel = interaction.user.voice.channel

        # Connect with VoiceRecvClient
        if interaction.guild.voice_client:
            if not isinstance(
                interaction.guild.voice_client, voice_recv.VoiceRecvClient
            ):
                await interaction.guild.voice_client.disconnect()
                vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
            else:
                if interaction.guild.voice_client.channel != channel:
                    await interaction.guild.voice_client.move_to(channel)
                vc = interaction.guild.voice_client
        else:
            vc = await channel.connect(cls=voice_recv.VoiceRecvClient)

        await interaction.response.send_message(
            f"{channel.name}에서 대화를 시작합니다. 말을 멈추면 자동으로 STT 결과가 전송됩니다.",
            ephemeral=True,
        )

        if interaction.user.id in self.active_chats:
            self.active_chats[interaction.user.id].cancel()

        task = self.bot.loop.create_task(self.chat_loop(interaction.user, vc))
        self.active_chats[interaction.user.id] = task

    @app_commands.command(
        name="대화종료", description="실시간 대화를 종료하고 봇을 퇴장시킵니다."
    )
    async def stop_chat(self, interaction: discord.Interaction):
        if interaction.user.id in self.active_chats:
            self.active_chats[interaction.user.id].cancel()
            del self.active_chats[interaction.user.id]

        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message(
                "대화를 종료했습니다.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "봇이 음성 채널에 없습니다.", ephemeral=True
            )

    async def chat_loop(self, command_user, vc):
        await self.load_model()
        print(f"[DEBUG] chat_loop started for {command_user.name}")

        try:
            while vc.is_connected():
                print("[DEBUG] Starting recording cycle")

                sink = StreamingSink(self, command_user, vc)
                vc.listen(sink)
                print("[DEBUG] vc.listen(sink) called with VAD")

                # Keep running until disconnected or cancelled
                while vc.is_connected():
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("[DEBUG] chat_loop cancelled")
            if vc.is_listening():
                vc.stop_listening()
        except Exception as e:
            print(f"[DEBUG] Chat loop error: {e}")
            traceback.print_exc()
            if vc.is_listening():
                vc.stop_listening()

    async def process_audio(self, filepath, speaker, recipient, vc):
        print(
            f"[DEBUG] process_audio started. File: {filepath}, Speaker: {speaker.name}"
        )
        try:
            # Check if file has data (header is 44 bytes)
            file_size = os.path.getsize(filepath)
            print(f"[DEBUG] File size: {file_size} bytes")
            if file_size <= 44:
                print("[DEBUG] File is empty (only header). Skipping.")
                return

            print("[DEBUG] Starting transcription...")
            text = await self.transcribe(filepath)
            print(f"[DEBUG] Transcription result: '{text}'")

            if text.strip():
                # Filter out hallucinations
                hallucinations = [
                    "한국어와 영어를 자연스럽게 섞어서 사용하는 대화입니다.",
                    "MBC News",
                    "Thank you for watching",
                    "Subtitles by",
                ]
                if any(h in text for h in hallucinations):
                    print(f"[DEBUG] Filtered hallucination: {text}")
                    return

                try:
                    await recipient.send(f"[{speaker.display_name}] STT: {text}")
                except discord.Forbidden:
                    print(f"Cannot send DM to {recipient.name}")

                # TTS Playback (Commented out)
                # ...

        except Exception as e:
            print(f"Processing Error: {e}")
            traceback.print_exc()
        finally:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except:
                    pass

    async def transcribe(self, filepath):
        loop = asyncio.get_event_loop()
        async with self.transcribe_lock:
            # language=None allows auto-detection (supports both Korean and English)
            # initial_prompt helps guide the model context
            result = await loop.run_in_executor(
                None,
                lambda: self.model.transcribe(
                    filepath,
                    language=None,
                    initial_prompt="한국어와 영어를 자연스럽게 섞어서 사용하는 대화입니다.",
                    no_speech_threshold=0.6,
                    logprob_threshold=-1.0,
                ),
            )
        return result["text"]

    async def generate_tts(self, text):
        loop = asyncio.get_event_loop()

        def _create_tts():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_filename = f.name

            engine = pyttsx3.init()
            engine.save_to_file(text, temp_filename)
            engine.runAndWait()
            return temp_filename

        return await loop.run_in_executor(None, _create_tts)

    def cleanup_tts(self, filepath):
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Error cleaning up TTS file: {e}")


async def setup(bot):
    await bot.add_cog(VoiceChat(bot))
