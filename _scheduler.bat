@echo off
REM 현재 배치 파일이 있는 디렉토리를 root로 지정
set "root=%~dp0"
cd /d "%root%"

REM 가상환경 활성화
call "%root%\.venv\Scripts\activate.bat"

REM 봇 실행
python _autoPullAndLaunch.py

pause
