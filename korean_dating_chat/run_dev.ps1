# 로컬 개발 서버 실행 (자동 리로드)
# 사용: korean_dating_chat 폴더에서  ->  .\run_dev.ps1
# 브라우저: http://localhost:8080  (편집하면 자동 반영, 새로고침)
# 중지: 이 터미널에서 Ctrl+C

# 1) 8080 점유 중인 옛 서버 정리 (스테일 서버가 옛 화면 서빙하는 문제 방지)
Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object {
    Write-Host "포트 8080 점유 프로세스(PID $_) 종료"
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
  }

# 2) .env 없으면 안내
if (-not (Test-Path .env)) {
  Write-Host ".env 가 없습니다. '.env.example' 을 복사해서 키를 채우세요:" -ForegroundColor Yellow
  Write-Host "  Copy-Item .env.example .env   그리고 GEMINI_API_KEY 등 입력" -ForegroundColor Yellow
}

# 3) 개발 서버 기동 (자동 리로드 ON, dev-login 활성)
$env:FLASK_DEBUG = "1"
Write-Host "개발 서버 시작 -> http://localhost:8080  (Ctrl+C 로 중지)" -ForegroundColor Green
python chatbot.py
