import os
import subprocess
import time
from datetime import datetime


# 로컬 변경사항이 있는지 확인(unstaged/uncommitted)
def has_local_changes():
    result = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True
    )
    return bool(result.stdout.strip())


# git pull을 실행하여 결과를 반환하는 함수
# git stash 후 git pull을 실행하여 결과를 반환하는 함수
def git_stash_and_pull():
    # 1) 로컬 변경사항이 있으면 stash
    if has_local_changes():
        print(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Local changes detected. Stashing..."
        )
        stash_res = subprocess.run(
            ["git", "stash", "push", "-u", "-m", "auto-stash_before_pull"],
            capture_output=True,
            text=True,
        )
        print(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} git stash output: {stash_res.stdout.strip()}"
        )

    # 2) git pull 실행
    pull_res = subprocess.run(["git", "pull"], capture_output=True, text=True)
    pull_output = pull_res.stdout.strip()
    print(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} git pull output: {pull_output}"
    )

    return pull_output


# launch.bat을 실행하는 함수 (새 콘솔 창에서 실행)
# def start_launch_bat():
#     bat_path = os.path.join(os.getcwd(), "_launchBot.bat")
#     proc = subprocess.Popen(
#         ["cmd", "/c", bat_path], creationflags=subprocess.CREATE_NEW_CONSOLE
#     )
#     return proc


def start_launch_ps1():
    # 현재 작업 디렉토리에서 실행할 PS1 경로 지정
    ps1_path = os.path.join(os.getcwd(), "_launchBot.ps1")

    proc = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ps1_path,
        ],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
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
    # launch.ps1 프로세스 시작
    process = start_launch_ps1()
    print(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} launch.ps1 started, PID: {process.pid}"
    )

    # 일정 시간 간격 (예: 5분 = 300초)으로 git pull 실행
    check_interval = 300

    while True:
        output = git_stash_and_pull()
        print(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} git pull output: {output}"
        )

        # "Already up to date" 메시지가 없으면 변경사항이 발생한 것으로 간주
        if "Already up to date" not in output:
            print(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Changes detected. Restarting launch.bat process..."
            )

            kill_process(process)
            # 변경사항 감지 후 잠깐 대기 (옵션)
            time.sleep(5)
            process = start_launch_bat()
            print(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} launch.bat restarted, PID: {process.pid}"
            )

        else:
            print(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} No changes detected."
            )

        time.sleep(check_interval)


if __name__ == "__main__":
    main()
