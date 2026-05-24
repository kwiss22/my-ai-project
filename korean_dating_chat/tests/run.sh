#!/usr/bin/env bash
# 통합 회귀 — 한 서버 인스턴스에서 regression.mjs 실행.
#
# 사용:
#   ./tests/run.sh                # 기본 (port 8080)
#   PORT=9090 ./tests/run.sh
#   GEMINI_API_KEY=sk-... ./tests/run.sh   # 실 API 키 주입 가능 (선택)
#
# 환경:
#   회귀에 필요한 ENV 를 모두 export 한 뒤 chatbot.py 실행.
#   끝나면 서버 깨끗하게 종료.

set -e
cd "$(dirname "$0")/.."

PORT="${PORT:-8080}"
KEEP_SERVER="${KEEP_SERVER:-0}"   # 1 이면 회귀 후 서버 살려두기 (디버그용)

# 회귀가 가정하는 canonical 환경
export GEMINI_API_KEY="${GEMINI_API_KEY:-dev_placeholder}"
export DAILY_FREE_QUOTA=5
export STRIPE_TRIAL_DAYS=7
export STRIPE_WEBHOOK_SECRET=whsec_local_test_123
export ADMIN_EMAILS=admin@example.com
export RATELIMIT_BYPASS_TOKEN=test_bypass
export ALERT_TEST_SINK=1
export ALERT_MIN_SEVERITY=critical
export ALERT_DEDUP_SECONDS=300
export ENV_ALLOW_TEST_RESET=1
export PRICE_USD_MONTHLY=4.99
export ENABLE_VOCAB_EXTRACTION=false
export PORT

# 이전 인스턴스 / DB 정리
pkill -f "python3 chatbot.py" 2>/dev/null || true
sleep 1
rm -f kdate_users.db events.jsonl

# 서버 백그라운드 시작
echo "[run.sh] starting server on :$PORT"
python3 chatbot.py > /tmp/regression-server.log 2>&1 &
SERVER_PID=$!

cleanup() {
    if [ "$KEEP_SERVER" = "1" ]; then
        echo "[run.sh] KEEP_SERVER=1 → 서버 유지 (PID=$SERVER_PID, log=/tmp/regression-server.log)"
        return
    fi
    echo "[run.sh] stopping server (PID=$SERVER_PID)"
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
}
trap cleanup EXIT

# 헬스체크 — 최대 15초 대기
echo "[run.sh] waiting for :$PORT/me ..."
for i in $(seq 1 30); do
    if curl -sf -o /dev/null "http://127.0.0.1:$PORT/me"; then
        echo "[run.sh] server up"
        break
    fi
    sleep 0.5
done

# 테스트 실행
node tests/regression.mjs
EXIT=$?

exit $EXIT
