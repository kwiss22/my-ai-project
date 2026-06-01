# 결제·인증 셋업 가이드

이 문서는 실제 PayPal / Google OAuth 키를 발급받아 프로덕션에 연결하는
단계별 절차입니다. 코드는 이미 다 들어가 있고, 키만 채우면 동작합니다.

## 0. 사전 확인

```bash
# /me 가 응답하면 서버는 살아있음
curl -s https://your-domain.com/me | jq

# billing_enabled / login_methods 가 모두 false 면 키 미설정 상태
```

## 1. PayPal (월 구독)

### 1.1 PayPal Business 계정 + 개발자 앱

1. https://www.paypal.com/kr/business 에서 **Business** 계정 가입 (한국 사업자 가능)
2. https://developer.paypal.com 로그인 → My Apps & Credentials
3. **Sandbox** 토글 (테스트) → Apps → Create App
   - App Name: `K-Dating Chat`
   - Type: Merchant
4. 표시되는 **Client ID** 복사 → `PAYPAL_CLIENT_ID`
5. **Secret** 복사 → `PAYPAL_CLIENT_SECRET`
6. 운영 전환 시 **Live** 토글에서 동일 절차 반복 (별도 Live Client ID/Secret)

### 1.2 Product + Billing Plan 생성

PayPal 은 **Catalog Product** + **Billing Plan** 2단계 구조입니다.

```bash
# 1) Product 생성 (1회만)
curl -X POST https://api-m.sandbox.paypal.com/v1/catalogs/products \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "K-Dating Chat 월 구독",
    "type": "SERVICE",
    "category": "ONLINE_GAMING"
  }'
# 응답의 "id" (PROD-XXX) 메모

# 2) Plan 생성 — 월 $4.99
curl -X POST https://api-m.sandbox.paypal.com/v1/billing/plans \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "PROD-XXX",
    "name": "K-Dating Chat Monthly",
    "billing_cycles": [{
      "frequency": {"interval_unit": "MONTH", "interval_count": 1},
      "tenure_type": "REGULAR",
      "sequence": 1,
      "total_cycles": 0,
      "pricing_scheme": {"fixed_price": {"value": "4.99", "currency_code": "USD"}}
    }],
    "payment_preferences": {"auto_bill_outstanding": true}
  }'
# 응답의 "id" (P-XXX) → PAYPAL_PLAN_ID
```

UI 로 만들 수도 있음: https://www.paypal.com → 결제 → 구독 → 플랜 만들기.

### 1.3 Webhook 등록

운영 도메인 결정 후:
1. Developer Dashboard → My Apps → 해당 앱 → Webhooks → Add Webhook
2. Webhook URL: `https://your-domain.com/billing/webhook`
3. 이벤트 7종 체크:
   - `BILLING.SUBSCRIPTION.ACTIVATED`
   - `BILLING.SUBSCRIPTION.UPDATED`
   - `BILLING.SUBSCRIPTION.CANCELLED`
   - `BILLING.SUBSCRIPTION.EXPIRED`
   - `BILLING.SUBSCRIPTION.SUSPENDED`
   - `BILLING.SUBSCRIPTION.PAYMENT.FAILED`
   - `PAYMENT.SALE.COMPLETED`
4. 저장 후 표시되는 **Webhook ID** (`WH-XXX`) → `PAYPAL_WEBHOOK_ID`

### 1.4 로컬 테스트 (서명 검증 우회)

```bash
# 시뮬레이터는 PayPal API 호출 없이 우리 webhook 핸들러에 payload 직접 POST.
# 서명 검증을 우회하려면:
export PAYPAL_WEBHOOK_TEST_BYPASS=1
export PAYPAL_CLIENT_ID=dev_placeholder
export PAYPAL_CLIENT_SECRET=dev_placeholder
export PAYPAL_PLAN_ID=P-TEST-LOCAL
export PAYPAL_WEBHOOK_ID=WH-TEST-LOCAL
GEMINI_API_KEY=dev_placeholder python3 chatbot.py

# 별도 셸 — 시뮬레이터로 lifecycle 검증
python3 tools/billing_simulate.py activate \
    --user-id USER_ID_FROM_DEVLOGIN \
    --subscription I-TEST-LOCAL-1 \
    --payer-id PAYER-TEST-1

python3 tools/billing_simulate.py update \
    --subscription I-TEST-LOCAL-1 \
    --status ACTIVE --days 30

# /me 확인 — subscription.active = true 가 돼야 함
```

### 1.5 진짜 결제 한 번 통과시키기 (Sandbox)

1. 위 환경변수 (실 Sandbox Client ID/Secret/Plan ID/Webhook ID) 로 서버 기동
2. 브라우저로 `/chat` 진입 → 로그인 → 페이월 모달 강제 트리거 (`DAILY_FREE_QUOTA=1`로 낮춰 1메시지 보내면 바로 페이월)
3. "구독 시작" → PayPal Sandbox 승인 페이지로 리다이렉트
4. Sandbox 테스트 구매자 계정 (https://developer.paypal.com → Testing Tools → Sandbox accounts) 으로 로그인
5. 승인 → `/chat?billing=success` 로 돌아옴 → 헤더 "✨ 무제한" 칩 표시
6. 무제한 메시지 보내기 가능

⚠️ 로컬은 PayPal 이 webhook 을 직접 보낼 수 없음. **Webhook simulator** 사용:
https://developer.paypal.com → Testing Tools → Webhooks Simulator
또는 ngrok 등으로 로컬을 인터넷에 노출.

## 2. Google OAuth

### 2.1 OAuth 동의 화면

1. https://console.cloud.google.com → 프로젝트 생성
2. APIs & Services → OAuth consent screen
   - User Type: External
   - App name, support email, developer email 입력
   - Scopes: `email`, `profile`, `openid` (기본)
3. Test users 에 본인 Google 계정 추가 (출시 전엔 Test users 만 로그인 가능)

### 2.2 OAuth 클라이언트 발급

1. APIs & Services → Credentials → Create credentials → OAuth client ID
2. Application type: **Web application**
3. Authorized redirect URIs:
   - `http://localhost:8080/auth/google/callback` (로컬)
   - `https://your-domain.com/auth/google/callback` (운영)
4. 발급된 **Client ID** → `GOOGLE_OAUTH_CLIENT_ID`
5. 발급된 **Client secret** → `GOOGLE_OAUTH_CLIENT_SECRET`

## 4. 최종 환경변수 모음

운영 배포 전 모두 설정:

```bash
# 세션
SESSION_SECRET=<openssl rand -hex 32 결과>     # ⚠️ 한 번 정하면 절대 변경 X
APP_BASE_URL=https://your-domain.com           # https 필수

# Quota
DAILY_FREE_QUOTA=25
QUOTA_TIMEZONE=Asia/Seoul                       # (향후, 현재는 UTC)

# Google
GOOGLE_OAUTH_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxx

# PayPal
PAYPAL_CLIENT_ID=AYY...                         # Live or Sandbox
PAYPAL_CLIENT_SECRET=EHH...
PAYPAL_PLAN_ID=P-xxx
PAYPAL_WEBHOOK_ID=WH-xxx
PAYPAL_API_BASE=https://api-m.paypal.com        # Sandbox: https://api-m.sandbox.paypal.com
PAYPAL_TRIAL_DAYS=7                             # 0 = trial 비활성. 7~14 권장.
PRICE_USD_MONTHLY=4.99                          # MRR 계산용. Plan 가격과 일치시키기.

# Prod 잠금
FLASK_ENV=production                            # DEV_LOGIN_ENABLED 자동 OFF
DEV_LOGIN_ENABLED=0                             # 명시적으로도 OFF

# 운영자 알림 (선택, 미설정 시 no-op)
ALERT_MIN_SEVERITY=critical                     # critical/error/warn/info
ALERT_DEDUP_SECONDS=300                         # 같은 kind 알림 묶기

# 이메일 (예: Gmail 앱 비밀번호)
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587                             # 465 이면 SMTP_SSL 자동
ALERT_SMTP_USER=ops@your-domain.com
ALERT_SMTP_PASSWORD=<16자리 앱 비밀번호>
ALERT_SMTP_FROM=ops@your-domain.com
ALERT_EMAIL_TO=ops@your-domain.com,founder@your-domain.com

# Slack incoming webhook
ALERT_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## 알림 채널 설정 (선택)

`critical` 이벤트(웹훅 서명 검증 실패·결제 3회 연속 실패 등) 발생 시 자동 알림.

### Slack incoming webhook
1. Slack workspace → 채널 → "Integrations" → "Add apps" → "Incoming Webhooks"
2. 활성화 후 표시되는 webhook URL → `ALERT_SLACK_WEBHOOK_URL`

### Gmail (개인·소규모)
1. Google 계정 → 2단계 인증 ON
2. "앱 비밀번호" 생성 → `ALERT_SMTP_PASSWORD`
3. `ALERT_SMTP_HOST=smtp.gmail.com`, `ALERT_SMTP_PORT=587`,
   `ALERT_SMTP_USER=<gmail 주소>`, `ALERT_EMAIL_TO=<수신 주소>`

### 작동 확인
```bash
curl https://your-domain.com/admin/alerts-health \
  -H "Cookie: kdate_session=..."
# {"any_enabled": true, "channels": {"slack": true, "smtp": false, ...}}
```

## 5. 운영 후 모니터링

- PayPal Developer Dashboard → Webhooks → Webhook Events 에서 전달 상태 확인
- 서버 로그 검색: `grep "\[BILLING\]" server.log`
- 사용자 quota 도달자 추세: SQLite 쿼리
  ```sql
  SELECT COUNT(*) FROM users
  WHERE daily_reset_date = date('now')
    AND daily_chat_count >= 25
    AND (subscription_status IS NULL OR subscription_status != 'active');
  ```

## 6. 문제 발생 시 체크리스트

| 증상 | 원인 후보 |
|---|---|
| 로그인 모달의 Google 버튼이 안 보임 | 환경변수 미설정. `/me` 응답의 `login_methods` 확인 |
| Google 로그인 후 "state mismatch" | redirect URI 가 Google Console 등록과 다름. 정확한 경로 + 포트 확인 |
| Checkout 페이지가 안 열림 (`/billing/checkout` → 503) | `PAYPAL_CLIENT_ID`/`PAYPAL_CLIENT_SECRET`/`PAYPAL_PLAN_ID` 중 하나 미설정 |
| 결제 완료 후에도 quota 초과 메시지 | webhook 미도착. PayPal Dashboard → Webhook Events 확인. `PAYPAL_WEBHOOK_ID` 일치 확인. |
| Webhook 401 / signature_invalid | `PAYPAL_WEBHOOK_ID` 가 등록한 webhook 의 ID 와 다름. Dashboard 에서 재확인. |
| 운영에서 Dev login 노출 | `FLASK_ENV=production` 누락. 즉시 설정 후 재배포. |
