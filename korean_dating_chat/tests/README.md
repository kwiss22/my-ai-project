# 회귀 테스트

`tests/run.sh` 한 번이면 결제·구독·인증·rate-limit·이벤트·알림 핵심 전부 통합 검증.

## 실행

```bash
# 기본 (port 8080, dev_placeholder 키)
./tests/run.sh

# 다른 포트
PORT=9090 ./tests/run.sh

# 실 API 키 주입 (선택)
GEMINI_API_KEY=sk-... ./tests/run.sh

# 회귀 후 서버 유지 (수동 디버그)
KEEP_SERVER=1 ./tests/run.sh
```

## 동작

1. 이전 서버 인스턴스·DB·events 파일 정리
2. canonical 환경(아래)으로 `chatbot.py` 백그라운드 시작
3. `:PORT/me` health-check 대기 (최대 15초)
4. `tests/regression.mjs` 실행 — 섹션 7개, 33+ 체크
5. 종료 시 서버 깨끗하게 kill (`KEEP_SERVER=1` 이면 유지)

## Canonical 환경

```
DAILY_FREE_QUOTA=5
STRIPE_TRIAL_DAYS=7
STRIPE_WEBHOOK_SECRET=whsec_local_test_123
ADMIN_EMAILS=admin@example.com
RATELIMIT_BYPASS_TOKEN=test_bypass
ALERT_TEST_SINK=1
ALERT_MIN_SEVERITY=critical
ENV_ALLOW_TEST_RESET=1
```

테스트 사이 격리는 `POST /admin/test-reset` 으로:
- `users` 테이블 비우기
- `events.jsonl` 삭제
- rate-limit 버킷 / alert dedup / test sink 초기화

운영(`FLASK_ENV=production`)에서는 503 으로 영구 차단.

## 통합된 회귀 섹션

| § | 검증 영역 |
|---|---|
| 1 | 미인증/인증 분기, /me 모양, /chat quota 차감 (1~5 + 6번째 페이월) |
| 2 | 구독 lifecycle: checkout → trialing → active → past_due → cancel_scheduled → canceled |
| 3 | rate-limit: /billing/checkout 5/min 정확 |
| 4 | /admin/stats + /admin/events 필터 + alerts-test sink |
| 5 | 계정 삭제 + admin 권한 (401/403) |
| 6 | Azure 미설정 시 /transcribe 503 그레이스풀 |
| 7 | 알림 환경 진단 (min_severity / dedup) |

## UI 회귀 (별도)

`/tmp/stt-check.mjs`, `/tmp/stt-fallback-check.mjs`, `/tmp/wonhwa-check.mjs`,
`/tmp/a11y-check.mjs` 는 Playwright 기반 UI 회귀. 환경 의존 없어서
독립 실행. `tests/run.sh` 서버가 떠 있는 동안 별도 셸에서 그대로 동작.

## CI 통합 (향후)

GitHub Actions 예시:
```yaml
- run: ./tests/run.sh
```
exit code 0 이면 모두 통과, 1 이면 실패 목록 stderr 로 출력.
