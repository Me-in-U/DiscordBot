import asyncio
import os
import tempfile
import wave
import discord
import traceback
from discord.ext import commands
from discord import app_commands
import whisper
import pyttsx3

# Try to import voice_recv, if not available, we can't do voice receive
try:
    from discord.ext import voice_recv
except ImportError:
    voice_recv = None


class MultiUserSink(voice_recv.AudioSink if voice_recv else object):
    def __init__(self):
        self.user_files = {}  # user -> {filename, wave_file, bytes}
        self.results = {}

    def wants_opus(self):
        return False

    def write(self, user, data):
        if user not in self.user_files:
            f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            f.close()  # Close handle so wave can open it

            wf = wave.open(f.name, "wb")
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(48000)

            self.user_files[user] = {"filename": f.name, "file": wf, "bytes": 0}
            print(f"[DEBUG] New stream for {user.name} ({user.id})")

        entry = self.user_files[user]
        entry["file"].writeframes(data.pcm)
        entry["bytes"] += len(data.pcm)

    def cleanup(self):
        if self.results:
            return self.results

        for user, entry in self.user_files.items():
            entry["file"].close()
            self.results[user] = entry["filename"]
            print(f"[DEBUG] Closed stream for {user.name}. Bytes: {entry['bytes']}")
        self.user_files = {}
        return self.results


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
            f"{channel.name}에서 대화를 시작합니다. 10초마다 STT 결과가 DM으로 전송됩니다.",
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

                sink = MultiUserSink()
                vc.listen(sink)
                print("[DEBUG] vc.listen(sink) called")

                await asyncio.sleep(10)
                print("[DEBUG] 10 seconds passed")

                vc.stop_listening()
                print("[DEBUG] vc.stop_listening() called")
                # Wait for file to be closed/written
                await asyncio.sleep(0.5)

                # Process files
                user_files = sink.cleanup()
                if not user_files:
                    print("[DEBUG] No audio recorded in this cycle.")

                for speaker, filename in user_files.items():
                    print(
                        f"[DEBUG] Processing audio for speaker: {speaker.name}, file: {filename}"
                    )
                    # We pass command_user as the recipient of the DM
                    self.bot.loop.create_task(
                        self.process_audio(filename, speaker, command_user, vc)
                    )

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
