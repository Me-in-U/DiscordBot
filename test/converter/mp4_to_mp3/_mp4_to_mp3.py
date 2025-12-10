import os
import subprocess
import sys


def _get_ffmpeg_path():
    """ffmpeg 실행 파일 경로를 찾습니다."""
    # 1. 현재 작업 디렉토리의 bin 폴더 확인
    cwd_bin = os.path.join(os.getcwd(), "bin", "ffmpeg.exe")
    if os.path.exists(cwd_bin):
        return cwd_bin

    # 2. 프로젝트 루트의 bin 폴더 확인 (이 스크립트가 test/converter/mp4_to_mp3/ 폴더에 있다고 가정)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # script_dir = .../test/converter/mp4_to_mp3
    # project_root = .../
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))

    root_bin = os.path.join(project_root, "bin", "ffmpeg.exe")
    if os.path.exists(root_bin):
        return root_bin

    # 3. 시스템 PATH 사용
    return "ffmpeg"


def convert_mp4_to_mp3(mp4_path: str, mp3_path: str = None):
    """
    MP4 파일을 MP3로 변환합니다.
    기본 출력 경로는 test/converter/extract.mp3 입니다.

    Args:
        mp4_path (str): 입력 MP4 파일 경로
        mp3_path (str, optional): 출력 MP3 파일 경로. 지정하지 않으면 test/converter/extract.mp3로 생성됩니다.
    """
    if not os.path.isfile(mp4_path):
        raise FileNotFoundError(f"'{mp4_path}' 파일을 찾을 수 없습니다.")

    if mp3_path is None:
        # 기본 경로: test/converter/extract.mp3
        script_dir = os.path.dirname(os.path.abspath(__file__))
        converter_dir = os.path.dirname(script_dir)
        mp3_path = os.path.join(converter_dir, "extract.mp3")

    ffmpeg_exe = _get_ffmpeg_path()

    ffmpeg_cmd = [
        ffmpeg_exe,
        "-i",
        mp4_path,
        "-vn",  # 비디오 스트림 제외
        "-acodec",
        "libmp3lame",
        "-q:a",
        "2",  # VBR 품질 (0-9, 2는 표준 고음질)
        "-y",  # 파일이 존재하면 덮어쓰기
        mp3_path,
    ]

    print(f"변환 시작: '{mp4_path}' -> '{mp3_path}'")
    try:
        # subprocess.run으로 ffmpeg 실행
        subprocess.run(
            ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        print("변환 완료!")
    except subprocess.CalledProcessError as e:
        print(f"변환 실패: {e}")
        if e.stderr:
            try:
                print(e.stderr.decode())
            except:
                print(e.stderr)


if __name__ == "__main__":
    # 커맨드라인 실행 예시: python test/mp4_to_mp3.py video.mp4
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        convert_mp4_to_mp3(input_file)
    else:
        print("사용법: python mp4_to_mp3.py <mp4_파일_경로>")
