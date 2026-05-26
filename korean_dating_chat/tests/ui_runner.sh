#!/usr/bin/env bash
# UI 회귀 테스트 — Playwright 기반.
# 자체 서버 시작 (다른 포트, regression.mjs 와 병렬 실행 가능)
# 후 tests/ui/*.mjs 순차 실행.
#
# 사용:
#   ./tests/ui_runner.sh           # PORT 9090 (regression.mjs 와 다름)
#   PORT=9999 ./tests/ui_runner.sh
#
# 사전:
#   npm 으로 playwright + chromium 설치 필요. CI 에서는 ci.yml 이 처리.
#   로컬에서는 ../node_modules/playwright 또는 글로벌 npm 에 설치.

set -e
cd "$(dirname "$0")/.."

PORT="${PORT:-9090}"

# playwright 브라우저 경로 — 로컬 dev VM 에 미리 다운로드된 chromium 사용.
# CI 에서는 `npx playwright install --with-deps chromium` 이 기본 경로에 배치.
if [ -d "/opt/pw-browsers" ] && [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ]; then
    export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
fi
# playwright 모듈 자체 — tests/node_modules 에 있으면 ESM 자동 해석 (Node ESM 은
# 현재 디렉토리 위로 거슬러 올라가며 node_modules 찾음).
if [ ! -d "tests/node_modules/playwright" ]; then
    echo "[ui_runner] tests/node_modules/playwright 없음 — 'cd tests && npm install' 실행 필요"
    exit 2
fi

# regression.mjs 와 동일한 canonical 환경
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

# UI 테스트용 별도 DB · 이벤트 경로 — regression.mjs 와 충돌 회피
export USERS_DB_PATH=/tmp/kdate_ui_test.db
export EVENTS_LOG_PATH=/tmp/kdate_ui_events.jsonl
export SNAPSHOTS_LOG_PATH=/tmp/kdate_ui_snapshots.jsonl
export PORT

rm -f "$USERS_DB_PATH" "$EVENTS_LOG_PATH" "$SNAPSHOTS_LOG_PATH"

echo "[ui_runner] starting server on :$PORT"
python3 chatbot.py > /tmp/ui-server.log 2>&1 &
SERVER_PID=$!

cleanup() {
    echo "[ui_runner] stopping server (PID=$SERVER_PID)"
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
    rm -f "$USERS_DB_PATH" "$EVENTS_LOG_PATH" "$SNAPSHOTS_LOG_PATH"
}
trap cleanup EXIT

# 헬스체크
echo "[ui_runner] waiting for :$PORT/me ..."
for i in $(seq 1 30); do
    if curl -sf -o /dev/null "http://127.0.0.1:$PORT/me"; then
        echo "[ui_runner] server up"
        break
    fi
    sleep 0.5
done

# 각 테스트 순차 실행 + 결과 집계
TESTS=(
    "seo-check.mjs"            # HTTP 만 — Playwright 불필요한 부분, 가장 빠름
    "onboarding-check.mjs"     # auth banner
    "admin-ui-check.mjs"       # admin dashboard
    "wonhwa-check.mjs"         # 캐릭터 카드 11명
    "stt-check.mjs"            # voice input native
    "a11y-check.mjs"           # 접근성 (가장 무거움)
)

PASS=0
FAIL=0
FAILED_LIST=()

for t in "${TESTS[@]}"; do
    echo ""
    echo "=========================================="
    echo "UI test: $t"
    echo "=========================================="
    if PORT=$PORT node tests/ui/$t; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        FAILED_LIST+=("$t")
    fi
done

echo ""
echo "=========================================="
echo "UI 회귀 결과: $PASS 통과 / $((PASS + FAIL)) 시도"
echo "=========================================="
if [ $FAIL -eq 0 ]; then
    echo "ALL UI TESTS PASSED"
    exit 0
else
    echo "FAILED:"
    for f in "${FAILED_LIST[@]}"; do
        echo "  - $f"
    done
    exit 1
fi
