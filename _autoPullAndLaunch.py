import subprocess
import time
import os
import signal


# git pull을 실행하여 결과를 반환하는 함수
def git_pull():
    result = subprocess.run(["git", "pull"], capture_output=True, text=True)
    return result.stdout.strip()


# launch.bat을 실행하는 함수 (새 콘솔 창에서 실행)
def start_launch_bat():
    # launch.bat이 현재 스크립트와 같은 디렉토리에 있다고 가정합니다.
    bat_path = os.path.join(os.getcwd(), "_launchBot.bat")
    proc = subprocess.Popen(
        ["cmd", "/c", bat_path], creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    return proc


# 실행 중인 프로세스를 종료하는 함수
def kill_process(proc):
    # taskkill 명령어를 사용하여 프로세스 트리 전체를 강제 종료
    subprocess.run(
        ["taskkill", "/PID", str(proc.pid), "/F", "/T"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    # launch.bat 프로세스 시작
    process = start_launch_bat()
    print(f"launch.bat started, PID: {process.pid}")

    # 일정 시간 간격 (예: 5분 = 300초)으로 git pull 실행
    check_interval = 300

    while True:
        output = git_pull()
        print("git pull output:", output)
        # "Already up to date" 메시지가 없으면 변경사항이 발생한 것으로 간주
        if "Already up to date" not in output:
            print("Changes detected. Restarting launch.bat process...")
            kill_process(process)
            # 변경사항 감지 후 잠깐 대기 (옵션)
            time.sleep(5)
            process = start_launch_bat()
            print(f"launch.bat restarted, PID: {process.pid}")
        else:
            print("No changes detected.")
        time.sleep(check_interval)


if __name__ == "__main__":
    main()
