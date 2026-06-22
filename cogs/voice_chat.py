from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import wave
import discord
import time
import numpy as np
from collections import deque
from discord.ext import commands
from discord import app_commands
from faster_whisper import WhisperModel
import pyttsx3

logger = logging.getLogger(__name__)

# Try to import voice_recv, if not available, we can't do voice receive
try:
    from discord.ext import voice_recv
except ImportError:
    voice_recv = None


class StreamingSink(voice_recv.AudioSink if voice_recv else object):
    def __init__(self, cog, command_user, vc) -> None:
        self.cog = cog
        self.command_user = command_user
        self.vc = vc
        self.user_buffers = {}  # user -> bytearray
        self.user_silence_start = {}  # user -> timestamp
        self.user_speaking = {}  # user -> bool
        self.user_pre_speech_buffer = {}  # user -> deque of bytes (ring buffer)

        # VAD Constants
        self.SILENCE_THRESHOLD = 700  # 600~800 추천 (환경 잡음 따라)
        self.SILENCE_DURATION = 0.6  # 0.6~1.0 추천
        self.MIN_SPEECH_DURATION = 0.25  # 0.25~0.40 추천
        self.PRE_SPEECH_BUFFER_DURATION = 0.2  # 0.2초 프리롤
        self.POST_SPEECH_BUFFER_DURATION = 0.2  # 0.2초 포스트롤

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data) -> None:
        # Calculate RMS
        pcm_data = np.frombuffer(data.pcm, dtype=np.int16).astype(np.float32)
        rms = np.sqrt(np.mean(pcm_data**2))
        now = time.time()

        if user not in self.user_buffers:
            self.user_buffers[user] = bytearray()
            self.user_speaking[user] = False
            self.user_silence_start[user] = now
            # 0.2s / 0.02s frame = 10 frames
            self.user_pre_speech_buffer[user] = deque(maxlen=10)

        # VAD Logic
        if rms > self.SILENCE_THRESHOLD:
            if not self.user_speaking[user]:
                # Just started speaking. Prepend the pre-speech buffer
                self.user_speaking[user] = True
                # Prepend pre-speech buffer (chunks)
                self.user_buffers[user].extend(
                    b"".join(self.user_pre_speech_buffer[user])
                )
                self.user_pre_speech_buffer[user].clear()

            self.user_silence_start[user] = now
            self.user_buffers[user].extend(data.pcm)
        else:
            # Silence
            if self.user_speaking[user]:
                # Was speaking, now silent. Keep recording for a bit (buffer silence)
                self.user_buffers[user].extend(data.pcm)

                # Check if silence exceeded threshold + post-roll duration
                if now - self.user_silence_start[user] > self.SILENCE_DURATION:
                    # Trim tail to keep only POST_SPEECH_BUFFER_DURATION (0.2s)
                    excess_time = (
                        now - self.user_silence_start[user]
                    ) - self.POST_SPEECH_BUFFER_DURATION
                    if excess_time > 0:
                        bytes_to_remove = int(excess_time * 48000 * 2 * 2)
                        if 0 < bytes_to_remove < len(self.user_buffers[user]):
                            self.user_buffers[user] = self.user_buffers[user][
                                :-bytes_to_remove
                            ]

                    self.flush_user(user)
            else:
                # Was silent, still silent.
                # Add to pre-speech ring buffer (frame)
                self.user_pre_speech_buffer[user].append(data.pcm)

    def flush_user(self, user) -> None:
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
        self.user_pre_speech_buffer[user].clear()

    def cleanup(self) -> None:
        pass


class VoiceChat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.model = None
        self.chat_data = {}  # guild_id -> {queue, message, task}
        self.active_chats = {}  # user_id -> task
        self.transcribe_lock = asyncio.Lock()

    async def load_model(self) -> None:
        # Ensure ffmpeg is in PATH
        ffmpeg_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "bin")
        )
        if ffmpeg_path not in os.environ["PATH"]:
            os.environ["PATH"] += os.pathsep + ffmpeg_path

        # Add NVIDIA library paths to PATH for Windows
        if os.name == "nt":
            try:
                import nvidia.cublas
                import nvidia.cudnn

                libs = [nvidia.cublas, nvidia.cudnn]
                for lib in libs:
                    for path in lib.__path__:
                        bin_path = os.path.join(path, "bin")
                        if os.path.exists(bin_path):
                            if bin_path not in os.environ["PATH"]:
                                os.environ["PATH"] += os.pathsep + bin_path
                                print(f"[DEBUG] Added NVIDIA library path: {bin_path}")
            except ImportError:
                print("[DEBUG] NVIDIA libraries not found in python environment.")
            except Exception:
                logger.exception("[DEBUG] Error adding NVIDIA paths")

        # Check if ffmpeg is actually callable
        import shutil

        if shutil.which("ffmpeg") is None:
            logger.warning("ffmpeg not found in PATH. Added path: %s", ffmpeg_path)
            if not os.path.exists(os.path.join(ffmpeg_path, "ffmpeg.exe")):
                logger.error("ffmpeg.exe not found in %s", ffmpeg_path)

        if self.model is None:
            print("Loading Whisper model...")
            loop = asyncio.get_event_loop()

            def _load_model():
                try:
                    print("Attempting to load Whisper model on GPU...")
                    return WhisperModel(
                        "deepdml/faster-whisper-large-v3-turbo-ct2",
                        device="cuda",
                        compute_type="float16",
                    )
                except Exception:
                    logger.warning(
                        "GPU load failed. Falling back to CPU (tiny model).",
                        exc_info=True,
                    )
                    return WhisperModel(
                        "tiny",
                        device="cpu",
                        compute_type="int8",
                    )

            self.model = await loop.run_in_executor(None, _load_model)
            print("Whisper model loaded.")

    @app_commands.command(
        name="대화",
        description="음성 채널에 봇을 초대하여 실시간 대화를 시작합니다.",
    )
    async def start_chat(self, interaction: discord.Interaction) -> None:
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

        # Initialize chat data
        status_msg = await interaction.channel.send("🎙️ **대화 시작**\n(대기 중...)")
        self.chat_data[interaction.guild.id] = {
            "queue": deque(maxlen=10),
            "message": status_msg,
            "task": self.bot.loop.create_task(self.display_loop(interaction.guild.id)),
        }

        if interaction.user.id in self.active_chats:
            self.active_chats[interaction.user.id].cancel()

        task = self.bot.loop.create_task(self.chat_loop(interaction.user, vc))
        self.active_chats[interaction.user.id] = task

    @app_commands.command(
        name="대화종료", description="실시간 대화를 종료하고 봇을 퇴장시킵니다."
    )
    async def stop_chat(self, interaction: discord.Interaction) -> None:
        if interaction.user.id in self.active_chats:
            self.active_chats[interaction.user.id].cancel()
            del self.active_chats[interaction.user.id]

        # Cleanup chat data
        if interaction.guild.id in self.chat_data:
            data = self.chat_data[interaction.guild.id]
            if "task" in data:
                data["task"].cancel()
            del self.chat_data[interaction.guild.id]

        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message(
                "대화를 종료했습니다.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "봇이 음성 채널에 없습니다.", ephemeral=True
            )

    async def chat_loop(self, command_user, vc) -> None:
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
        except Exception:
            logger.exception("[DEBUG] Chat loop error")
            if vc.is_listening():
                vc.stop_listening()

    async def process_audio(self, filepath: str, speaker, recipient, vc) -> None:
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
                # 4. 환각(Hallucination) 필터 조건부 수정
                file_size = os.path.getsize(filepath)
                duration = file_size / (48000 * 2 * 2)

                hallucinations = [
                    "자막",
                    "자막 제공",
                    "다음 영상",
                    "한글자막 by",
                    "감사합니다",
                    "고맙습니다",
                ]
                is_short = duration < 1.2
                has_keyword = any(h in text for h in hallucinations)

                if is_short and has_keyword:
                    print(
                        f"[DEBUG] Filtered hallucination: {text} (Duration: {duration:.2f}s)"
                    )
                    return

                # Add to queue instead of DM
                guild_id = vc.guild.id
                if guild_id in self.chat_data:
                    queue = self.chat_data[guild_id]["queue"]
                    timestamp = time.strftime("%H:%M:%S")
                    queue.append(f"[{timestamp}] **{speaker.display_name}**: {text}")
                else:
                    # Fallback to DM if chat data is missing
                    try:
                        await recipient.send(f"[{speaker.display_name}] STT: {text}")
                    except discord.Forbidden:
                        print(f"Cannot send DM to {recipient.name}")

                # TTS Playback (Commented out)
                # ...

        except Exception:
            logger.exception("Processing Error")
        finally:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    logger.warning("failed to remove temporary voice file: %s", filepath, exc_info=True)

    async def transcribe(self, filepath: str) -> str:
        loop = asyncio.get_event_loop()

        def _transcribe():
            segments, info = self.model.transcribe(
                filepath,
                language="ko",
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
                # 짧은 구간에서 이전 문맥에 끌려 반복되는 현상 완화
                condition_on_previous_text=False,
                # 모델 내부 VAD 활성화 (침묵 구간 필터링)
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            segments_list = list(segments)
            if not segments_list:
                return ""

            # 3. 결과 검증
            # segments의 no_speech_prob 평균값 사용
            avg_no_speech_prob = sum(s.no_speech_prob for s in segments_list) / len(
                segments_list
            )

            prob_threshold = 0.3 if info.duration < 0.7 else 0.6
            if avg_no_speech_prob > prob_threshold:
                print(
                    f"[DEBUG] Dropped: no_speech_prob {avg_no_speech_prob:.2f} > {prob_threshold}"
                )
                return ""

            return " ".join([segment.text for segment in segments_list])

        async with self.transcribe_lock:
            # language=None allows auto-detection (supports both Korean and English)
            # initial_prompt helps guide the model context
            text = await loop.run_in_executor(None, _transcribe)
        return text

    async def display_loop(self, guild_id: int) -> None:
        """Updates the status message every 3 seconds with the latest STT queue."""
        print(f"[DEBUG] display_loop started for guild {guild_id}")
        last_content = ""
        try:
            while guild_id in self.chat_data:
                data = self.chat_data[guild_id]
                queue = data["queue"]
                message = data["message"]

                if queue:
                    current_content = "🎙️ **실시간 대화 내용**\n" + "\n".join(queue)
                    if current_content != last_content:
                        try:
                            await message.edit(content=current_content)
                            last_content = current_content
                        except discord.NotFound:
                            print("[DEBUG] Status message deleted, stopping loop")
                            break
                        except Exception:
                            logger.warning("[DEBUG] Error editing message", exc_info=True)

                await asyncio.sleep(3)
        except asyncio.CancelledError:
            print(f"[DEBUG] display_loop cancelled for guild {guild_id}")
        except Exception:
            logger.exception("[DEBUG] display_loop error")

    async def generate_tts(self, text: str) -> str:
        loop = asyncio.get_event_loop()

        def _create_tts():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_filename = f.name

            engine = pyttsx3.init()
            engine.save_to_file(text, temp_filename)
            engine.runAndWait()
            return temp_filename

        return await loop.run_in_executor(None, _create_tts)

    def cleanup_tts(self, filepath: str) -> None:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                logger.warning("Error cleaning up TTS file: %s", filepath, exc_info=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceChat(bot))
