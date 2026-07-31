from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
import wave
import discord
import davey
import time
import numpy as np
from collections import deque
from discord.ext import commands
from discord import app_commands
from faster_whisper import WhisperModel

from .settings import (
    WhisperSettings,
    cpu_fallback_settings,
    resolve_whisper_settings,
)

logger = logging.getLogger(__name__)

# Try to import voice_recv, if not available, we can't do voice receive
try:
    from discord.ext import voice_recv
except ImportError:
    voice_recv = None


class StreamingSink(voice_recv.AudioSink if voice_recv else object):
    def __init__(self, cog, vc, session_id: str) -> None:
        super().__init__()
        self.cog = cog
        self.vc = vc
        self.session_id = session_id
        self.user_buffers = {}  # user -> bytearray
        self.user_silence_start = {}  # user -> timestamp
        self.user_speaking = {}  # user -> bool
        self.user_pre_speech_buffer = {}  # user -> deque of bytes (ring buffer)
        self.opus_decoders = {}  # SSRC -> decoder
        self.decode_error_counts = {}
        self.decode_error_last_logged = {}

        # VAD Constants
        self.SILENCE_THRESHOLD = 700  # 600~800 추천 (환경 잡음 따라)
        self.SILENCE_DURATION = 0.6  # 0.6~1.0 추천
        self.MIN_SPEECH_DURATION = 0.25  # 0.25~0.40 추천
        self.PRE_SPEECH_BUFFER_DURATION = 0.2  # 0.2초 프리롤
        self.POST_SPEECH_BUFFER_DURATION = 0.2  # 0.2초 포스트롤

    def wants_opus(self) -> bool:
        # voice_recv does not currently decrypt Discord DAVE media before
        # handing packets to its internal Opus decoder. Accept Opus here so
        # DAVE can be removed before decoding.
        return True

    def _record_decode_error(self, kind, user, ssrc, exc) -> None:
        count = self.decode_error_counts.get(kind, 0) + 1
        self.decode_error_counts[kind] = count

        now = time.monotonic()
        last_logged = self.decode_error_last_logged.get(kind, 0.0)
        if count != 1 and now - last_logged < 30:
            return

        self.decode_error_last_logged[kind] = now
        logger.warning(
            "Voice packet dropped: guild_id=%s user_id=%s ssrc=%s "
            "stage=%s error=%s count=%s",
            getattr(getattr(self.vc, "guild", None), "id", None),
            getattr(user, "id", None),
            ssrc,
            kind,
            type(exc).__name__,
            count,
        )

    def _decode_voice_packet(self, user, data) -> bytes | None:
        if user is None:
            return None

        packet = getattr(data, "packet", None)
        opus_data = getattr(data, "opus", None)
        if packet is None or not opus_data:
            return None

        ssrc = getattr(packet, "ssrc", None)
        if ssrc is None:
            return None

        connection = getattr(self.vc, "_connection", None)
        dave_session = getattr(connection, "dave_session", None)
        dave_protocol_version = getattr(connection, "dave_protocol_version", 0)
        if bool(packet) and dave_session is not None and dave_protocol_version:
            try:
                opus_data = dave_session.decrypt(
                    user.id,
                    davey.MediaType.audio,
                    opus_data,
                )
            except Exception as exc:
                self._record_decode_error("dave", user, ssrc, exc)
                return None

        if not opus_data:
            return None

        decoder = self.opus_decoders.get(ssrc)
        if decoder is None:
            decoder = discord.opus.Decoder()
            self.opus_decoders[ssrc] = decoder

        try:
            return decoder.decode(opus_data, fec=False)
        except discord.opus.OpusError as exc:
            # A single malformed or out-of-order frame must not terminate the
            # shared packet router. Recreate only the affected user's decoder.
            self.opus_decoders.pop(ssrc, None)
            self._record_decode_error("opus", user, ssrc, exc)
            return None

    def write(self, user, data) -> None:
        pcm = self._decode_voice_packet(user, data)
        if not pcm:
            return

        # Calculate RMS
        pcm_data = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if pcm_data.size == 0:
            return
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
            self.user_buffers[user].extend(pcm)
        else:
            # Silence
            if self.user_speaking[user]:
                # Was speaking, now silent. Keep recording for a bit (buffer silence)
                self.user_buffers[user].extend(pcm)

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
                self.user_pre_speech_buffer[user].append(pcm)

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
                self.cog.process_audio(
                    f.name,
                    user,
                    self.vc,
                    self.session_id,
                ),
                self.cog.bot.loop,
            )

        # Reset state
        self.user_buffers[user] = bytearray()
        self.user_speaking[user] = False
        self.user_pre_speech_buffer[user].clear()

    def cleanup(self) -> None:
        self.opus_decoders.clear()
        self.user_buffers.clear()
        self.user_silence_start.clear()
        self.user_speaking.clear()
        self.user_pre_speech_buffer.clear()


class VoiceChat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.model = None
        self.model_settings: WhisperSettings | None = None
        self.chat_data = {}  # guild_id -> {session_id, queue, message, task}
        self.active_chats = {}  # guild_id -> task
        self.model_load_lock = asyncio.Lock()
        self.transcribe_lock = asyncio.Lock()

    async def load_model(self) -> None:
        settings = resolve_whisper_settings()

        # Ensure ffmpeg is in PATH
        ffmpeg_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "bin")
        )
        process_path = os.environ.get("PATH", "")
        if ffmpeg_path not in process_path.split(os.pathsep):
            os.environ["PATH"] = (
                process_path + os.pathsep + ffmpeg_path
                if process_path
                else ffmpeg_path
            )

        # Add NVIDIA library paths to PATH for Windows
        if settings.device == "cuda" and os.name == "nt":
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

        async with self.model_load_lock:
            if self.model is not None:
                return

            logger.info(
                "Whisper model loading: model=%s device=%s compute_type=%s",
                settings.model,
                settings.device,
                settings.compute_type,
            )
            loop = asyncio.get_running_loop()

            def _load_model() -> tuple[object, WhisperSettings]:
                try:
                    return (
                        WhisperModel(
                            settings.model,
                            device=settings.device,
                            compute_type=settings.compute_type,
                        ),
                        settings,
                    )
                except Exception:
                    if settings.device != "cuda":
                        raise

                    fallback = cpu_fallback_settings()
                    logger.warning(
                        "Configured GPU model load failed. Falling back to "
                        "model=%s device=%s compute_type=%s.",
                        fallback.model,
                        fallback.device,
                        fallback.compute_type,
                        exc_info=True,
                    )
                    return (
                        WhisperModel(
                            fallback.model,
                            device=fallback.device,
                            compute_type=fallback.compute_type,
                        ),
                        fallback,
                    )

            self.model, self.model_settings = await loop.run_in_executor(
                None,
                _load_model,
            )
            logger.info(
                "Whisper model loaded: model=%s device=%s compute_type=%s",
                self.model_settings.model,
                self.model_settings.device,
                self.model_settings.compute_type,
            )

    @app_commands.command(
        name="대화",
        description="음성 채널에 봇을 초대하여 실시간 대화를 시작합니다.",
    )
    @app_commands.guild_only()
    async def start_chat(self, interaction: discord.Interaction) -> None:
        if voice_recv is None:
            await interaction.response.send_message(
                "discord-ext-voice-recv 모듈이 설치되지 않았습니다.", ephemeral=True
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있는 명령어입니다.", ephemeral=True
            )
            return

        voice_state = getattr(interaction.user, "voice", None)
        if voice_state is None:
            await interaction.response.send_message(
                "음성 채널에 먼저 입장해주세요.", ephemeral=True
            )
            return

        channel = voice_state.channel
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True, thinking=True)
        vc = None

        try:
            # Connect with VoiceRecvClient
            if guild.voice_client:
                if not isinstance(guild.voice_client, voice_recv.VoiceRecvClient):
                    await guild.voice_client.disconnect()
                    vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
                else:
                    if guild.voice_client.channel != channel:
                        await guild.voice_client.move_to(channel)
                    vc = guild.voice_client
            else:
                vc = await channel.connect(cls=voice_recv.VoiceRecvClient)

            self._cancel_guild_tasks(guild.id)
            if vc.is_listening():
                vc.stop_listening()

            status_msg = await interaction.channel.send(
                "🎙️ **대화 시작**\n(음성 인식 모델 준비 중...)"
            )
            session_id = uuid.uuid4().hex
            self.chat_data[guild.id] = {
                "session_id": session_id,
                "queue": deque(maxlen=10),
                "message": status_msg,
                "task": self.bot.loop.create_task(
                    self.display_loop(guild.id, session_id)
                ),
            }

            task = self.bot.loop.create_task(
                self.chat_loop(interaction.user, vc, guild.id, session_id)
            )
            self.active_chats[guild.id] = task
        except Exception:
            self._cancel_guild_tasks(guild.id)
            if vc is not None:
                try:
                    await vc.disconnect()
                except Exception:
                    logger.warning(
                        "실패한 음성 대화 연결 정리 실패: guild_id=%s",
                        guild.id,
                        exc_info=True,
                    )
            logger.exception(
                "음성 대화 시작 실패: guild_id=%s channel_id=%s",
                guild.id,
                getattr(channel, "id", None),
            )
            try:
                await interaction.followup.send(
                    "음성 채널 연결 또는 대화 준비에 실패했습니다. "
                    "봇의 연결 및 말하기 권한을 확인해주세요.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                logger.warning(
                    "음성 대화 시작 실패 응답 전송 실패: guild_id=%s",
                    guild.id,
                    exc_info=True,
                )
            return

        try:
            await interaction.followup.send(
                "음성 채널에 입장했습니다. 음성 인식 모델을 준비하고 있습니다.",
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.warning(
                "음성 대화 시작 응답 전송 실패: guild_id=%s",
                guild.id,
                exc_info=True,
            )

    @app_commands.command(
        name="대화종료", description="실시간 대화를 종료하고 봇을 퇴장시킵니다."
    )
    @app_commands.guild_only()
    async def stop_chat(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있는 명령어입니다.", ephemeral=True
            )
            return

        guild = interaction.guild
        voice_client = guild.voice_client
        if voice_client is None and guild.id not in self.active_chats:
            await interaction.response.send_message(
                "봇이 음성 채널에 없습니다.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        self._cancel_guild_tasks(guild.id)

        try:
            if voice_client is not None:
                if (
                    isinstance(voice_client, voice_recv.VoiceRecvClient)
                    and voice_client.is_listening()
                ):
                    voice_client.stop_listening()
                await voice_client.disconnect()
        except Exception:
            logger.exception("음성 대화 종료 실패: guild_id=%s", guild.id)
            await interaction.followup.send(
                "음성 대화를 정리하는 중 오류가 발생했습니다.",
                ephemeral=True,
            )
            return

        await interaction.followup.send("대화를 종료했습니다.", ephemeral=True)

    def _cancel_guild_tasks(self, guild_id: int) -> None:
        chat_task = self.active_chats.pop(guild_id, None)
        if chat_task is not None:
            chat_task.cancel()

        data = self.chat_data.pop(guild_id, None)
        if data is not None:
            display_task = data.get("task")
            if display_task is not None:
                display_task.cancel()

    def _get_chat_session(self, guild_id: int, session_id: str):
        data = self.chat_data.get(guild_id)
        if data is None or data.get("session_id") != session_id:
            return None
        return data

    async def chat_loop(
        self,
        command_user,
        vc,
        guild_id: int,
        session_id: str,
    ) -> None:
        current_task = asyncio.current_task()

        try:
            await self.load_model()
            data = self._get_chat_session(guild_id, session_id)
            if data is None:
                return

            try:
                await data["message"].edit(
                    content="🎙️ **대화 시작**\n(대기 중...)"
                )
            except discord.HTTPException:
                logger.warning(
                    "음성 대화 준비 상태 메시지 수정 실패: guild_id=%s",
                    guild_id,
                    exc_info=True,
                )

            print(f"[DEBUG] chat_loop started for {command_user.name}")
            while vc.is_connected():
                print("[DEBUG] Starting recording cycle")

                sink = StreamingSink(self, vc, session_id)
                receive_error = []

                def after_receive(error):
                    if error is not None:
                        receive_error.append(error)

                vc.listen(sink, after=after_receive)
                print("[DEBUG] vc.listen(sink) called with VAD")

                # Keep running until disconnected or cancelled
                while vc.is_connected() and vc.is_listening():
                    await asyncio.sleep(1)

                if vc.is_connected():
                    error = (
                        receive_error[-1]
                        if receive_error
                        else RuntimeError("voice receiver stopped")
                    )
                    raise RuntimeError(
                        "Voice receive loop stopped unexpectedly"
                    ) from error

        except asyncio.CancelledError:
            print("[DEBUG] chat_loop cancelled")
            if vc.is_listening():
                vc.stop_listening()
            raise
        except Exception:
            logger.exception("음성 대화 처리 실패: guild_id=%s", guild_id)
            if vc.is_listening():
                vc.stop_listening()
            data = self._get_chat_session(guild_id, session_id)
            if data is not None:
                try:
                    await data["message"].edit(
                        content=(
                            "🎙️ **대화 종료**\n"
                            "(음성 인식 모델 또는 수신 처리에 실패했습니다.)"
                        )
                    )
                except discord.HTTPException:
                    logger.warning(
                        "음성 대화 오류 상태 메시지 수정 실패: guild_id=%s",
                        guild_id,
                        exc_info=True,
                    )
            if vc.is_connected():
                try:
                    await vc.disconnect()
                except Exception:
                    logger.warning(
                        "오류 발생 후 음성 연결 해제 실패: guild_id=%s",
                        guild_id,
                        exc_info=True,
                    )
        finally:
            if self.active_chats.get(guild_id) is current_task:
                self.active_chats.pop(guild_id, None)
                data = self.chat_data.pop(guild_id, None)
                if data is not None:
                    display_task = data.get("task")
                    if display_task is not None:
                        display_task.cancel()

    async def process_audio(
        self,
        filepath: str,
        speaker,
        vc,
        session_id: str,
    ) -> None:
        print(
            f"[DEBUG] process_audio started. File: {filepath}, Speaker: {speaker.name}"
        )
        try:
            guild_id = vc.guild.id
            if self._get_chat_session(guild_id, session_id) is None:
                logger.debug(
                    "종료된 음성 대화의 전사 시작을 폐기합니다: guild_id=%s",
                    guild_id,
                )
                return

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

                data = self._get_chat_session(guild_id, session_id)
                if data is None:
                    logger.debug(
                        "종료된 음성 대화의 전사 결과를 폐기합니다: guild_id=%s",
                        guild_id,
                    )
                    return

                queue = data["queue"]
                timestamp = time.strftime("%H:%M:%S")
                queue.append(f"[{timestamp}] **{speaker.display_name}**: {text}")

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

    async def display_loop(self, guild_id: int, session_id: str) -> None:
        """Updates the status message every 3 seconds with the latest STT queue."""
        print(f"[DEBUG] display_loop started for guild {guild_id}")
        last_content = ""
        try:
            while True:
                data = self._get_chat_session(guild_id, session_id)
                if data is None:
                    break
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
            import pyttsx3

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
