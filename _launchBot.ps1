# 현재 스크립트 파일이 있는 디렉토리를 root로 지정
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 가상환경 활성화 (PowerShell용 activate 스크립트 호출)
& "$root\.venv\Scripts\Activate.ps1"

# 봇 실행
python bot.py

# 실행 결과 확인을 위한 일시 정지
Read-Host "`nPress Enter to exit..."
