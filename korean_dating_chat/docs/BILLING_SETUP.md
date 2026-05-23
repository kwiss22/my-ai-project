# 결제·인증 셋업 가이드

이 문서는 실제 Stripe / Google OAuth 키를 발급받아 프로덕션에 연결하는
단계별 절차입니다. 코드는 이미 다 들어가 있고, 키만 채우면 동작합니다.

## 0. 사전 확인

```bash
# /me 가 응답하면 서버는 살아있음
curl -s https://your-domain.com/me | jq

# billing_enabled / login_methods 가 모두 false 면 키 미설정 상태
```

## 1. Stripe (월 구독)

### 1.1 계정 + 상품 생성

1. https://dashboard.stripe.com 가입 (사업자 인증은 테스트 단계에선 생략 가능)
2. **Test mode** 토글 ON (좌상단)
3. Products → Add product
   - Name: `K-Dating Chat 월 구독`
   - Pricing: Recurring, Monthly, $4.99 (또는 ₩6,900)
   - 저장 후 표시되는 **Price ID** (`price_xxx...`) 복사 → `STRIPE_PRICE_ID`
4. Developers → API keys → **Secret key** (`sk_test_...`) 복사 → `STRIPE_SECRET_KEY`

### 1.2 Webhook 등록

운영 도메인 결정 후:
1. Developers → Webhooks → Add endpoint
2. Endpoint URL: `https://your-domain.com/billing/webhook`
3. 구독 이벤트 4종:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
4. 저장 후 표시되는 **Signing secret** (`whsec_...`) 복사 → `STRIPE_WEBHOOK_SECRET`

### 1.3 로컬 테스트 (Stripe CLI 없이)

```bash
# 임의의 webhook secret 으로 서버 기동
export STRIPE_WEBHOOK_SECRET=whsec_local_test_$(openssl rand -hex 16)
export STRIPE_SECRET_KEY=sk_test_xxx     # 진짜 테스트키 (Checkout 호출용)
export STRIPE_PRICE_ID=price_xxx
GEMINI_API_KEY=dev_placeholder python3 chatbot.py

# 별도 셸 — 시뮬레이터로 webhook flow 검증
python3 tools/billing_simulate.py checkout \
    --user-id USER_ID_FROM_DEVLOGIN \
    --customer cus_test_local_1 \
    --subscription sub_test_local_1

python3 tools/billing_simulate.py sub-update \
    --customer cus_test_local_1 \
    --subscription sub_test_local_1 \
    --status active --days 30 --created

# /me 확인 — subscription.active = true 가 돼야 함
```

### 1.4 진짜 Checkout 한 번 통과시키기

1. 위 환경변수 설정한 서버 기동
2. 브라우저로 `/chat` 진입 → 로그인 → 페이월 모달 강제 트리거 (`DAILY_FREE_QUOTA=1`로 낮춰 1메시지 보내면 바로 페이월)
3. "구독 시작" → Stripe Checkout 페이지로 리다이렉트
4. 테스트 카드 번호: `4242 4242 4242 4242`, 만료 미래 임의, CVC 임의
5. 결제 완료 → `/chat?billing=success` 로 돌아옴 → 헤더 "✨ 무제한" 칩 표시
6. 무제한 메시지 보내기 가능

⚠️ 로컬 테스트 시 **실제 Stripe → 로컬 webhook 전달**은 `stripe listen` CLI 필요:
```bash
stripe listen --forward-to localhost:8080/billing/webhook
# 표시되는 whsec_xxx 을 STRIPE_WEBHOOK_SECRET 으로 재설정
```

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

# Stripe
STRIPE_SECRET_KEY=sk_live_xxx                   # 또는 sk_test_xxx
STRIPE_PRICE_ID=price_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Prod 잠금
FLASK_ENV=production                            # DEV_LOGIN_ENABLED 자동 OFF
DEV_LOGIN_ENABLED=0                             # 명시적으로도 OFF
```

## 5. 운영 후 모니터링

- Stripe Dashboard → Events 에서 webhook 전달 상태 확인
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
| Checkout 페이지가 안 열림 (`/billing/checkout` → 503) | `STRIPE_SECRET_KEY` 또는 `STRIPE_PRICE_ID` 미설정 |
| 결제 완료 후에도 quota 초과 메시지 | webhook 미도착. Stripe Dashboard → Events 확인. 서명 비밀키 일치 확인. |
| 운영에서 Dev login 노출 | `FLASK_ENV=production` 누락. 즉시 설정 후 재배포. |
