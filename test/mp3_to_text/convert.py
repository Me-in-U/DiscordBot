# ── 수정본: voice.mp3 를 voice.txt 로 변환하는 독립 스크립트 ──
import os
import whisper


def mp3_to_txt(mp3_file: str, txt_file: str = "video.txt"):
    # 1) 파일 존재 확인
    if not os.path.isfile(mp3_file):
        raise FileNotFoundError(f"'{mp3_file}' 파일을 찾을 수 없습니다.")

    # 2) Whisper 모델 로드 (tiny 모델, CPU)
    model = whisper.load_model("tiny").to("cpu")

    # 3) MP3 → 텍스트 변환
    result = model.transcribe(mp3_file)
    text = result["text"].strip()

    # 4) 결과를 파일로 저장
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"'{mp3_file}' → '{txt_file}' 변환 완료. 총 {len(text)}자")


if __name__ == "__main__":
    mp3_to_txt("video.mp3", "voice.txt")
