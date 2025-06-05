# 1) 현재 스크립트 파일이 있는 디렉토리를 root로 지정
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 2) 가상환경 활성화
#    - PowerShell에서는 activate.ps1을 호출해야 함
& "$root\.venv\Scripts\Activate.ps1"

# 3) 봇 실행
python bot.py

# 4) 실행 결과 확인을 위해 일시 정지 (PowerShell에서는 Read-Host 사용)
Read-Host "`nPress Enter to exit..."
