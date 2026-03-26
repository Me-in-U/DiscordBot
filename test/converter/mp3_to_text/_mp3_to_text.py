# ── 수정본: voice.mp3 를 voice.txt 로 변환하는 독립 스크립트 ──
import os

from faster_whisper import WhisperModel


def mp3_to_txt(mp3_file: str = None, txt_file: str = None):
    # 경로 설정
    script_dir = os.path.dirname(os.path.abspath(__file__))
    converter_dir = os.path.dirname(script_dir)

    if mp3_file is None:
        mp3_file = os.path.join(converter_dir, "extract.mp3")

    if txt_file is None:
        txt_file = os.path.join(converter_dir, "stt.txt")

    # 1) 파일 존재 확인
    if not os.path.isfile(mp3_file):
        raise FileNotFoundError(f"'{mp3_file}' 파일을 찾을 수 없습니다.")

    print(f"변환 시작: '{mp3_file}' -> '{txt_file}'")

    # 2) faster-whisper 모델 로드 (GPU 우선, 실패 시 CPU fallback)
    try:
        model = WhisperModel(
            "deepdml/faster-whisper-large-v3-turbo-ct2",
            device="cuda",
            compute_type="float16",
        )
    except Exception:
        print("⚠️ CUDA를 사용할 수 없어 CPU로 실행합니다. (속도가 느릴 수 있음)")
        model = WhisperModel("tiny", device="cpu", compute_type="int8")

    # 3) MP3 → 텍스트 변환
    segments, _info = model.transcribe(
        mp3_file,
        language="ko",
        condition_on_previous_text=False,
        vad_filter=True,
    )
    text = " ".join(segment.text.strip() for segment in segments if segment.text)

    # 4) 결과를 파일로 저장
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"변환 완료. 총 {len(text)}자")


if __name__ == "__main__":
    mp3_to_txt()
