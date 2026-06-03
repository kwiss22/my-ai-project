"""PayPal Subscription 인프라 1회 셋업 — Catalog Product + Billing Plan 생성.

PayPal 은 구독을 다음 3단계로 모델링:
  1. Catalog Product — '무엇을 파는지' (앱·서비스 단위, 1회만 만들면 됨)
  2. Billing Plan    — 가격·주기·trial 정의 (Product 에 attach. 가격 바꾸려면 새 plan)
  3. Subscription    — 사용자가 결제할 때마다 PayPal 이 생성 (자동)

이 스크립트는 1, 2 단계를 자동화. 결과로 PRODUCT_ID + PLAN_ID 출력.
PLAN_ID 를 환경변수 PAYPAL_PLAN_ID 로 등록하면 우리 코드가 그걸로 결제 시작.

사용:
    # 환경변수 export 필수
    export PAYPAL_CLIENT_ID=...
    export PAYPAL_CLIENT_SECRET=...
    export PAYPAL_API_BASE=https://api-m.sandbox.paypal.com   # 또는 production
    export PAYPAL_PRICE_USD=4.99                               # (선택) 기본 4.99
    export PAYPAL_PRODUCT_NAME="K-Dating Chat 월 구독"          # (선택)
    export PAYPAL_PLAN_NAME="Monthly Unlimited"                 # (선택)
    export PAYPAL_TRIAL_DAYS=7                                  # (선택) 0 = trial 없음

    python3 tools/paypal_setup.py

배포 환경 (Sandbox vs Live) 은 PAYPAL_API_BASE 로만 구분. Live 키는 절대 Sandbox base
와 섞이면 안 됨 (PayPal 이 401 응답).
"""
import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error

API_BASE = os.getenv('PAYPAL_API_BASE', 'https://api-m.sandbox.paypal.com').rstrip('/')
CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', '')
PRICE_USD = os.getenv('PAYPAL_PRICE_USD', '4.99')
PRODUCT_NAME = os.getenv('PAYPAL_PRODUCT_NAME', 'K-Dating Chat 월 구독')
PLAN_NAME = os.getenv('PAYPAL_PLAN_NAME', 'Monthly Unlimited')
TRIAL_DAYS = int(os.getenv('PAYPAL_TRIAL_DAYS', '7'))


def _abort(msg, code=1):
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _request(method, path, body=None, headers=None):
    url = API_BASE + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'application/json')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8') if e.fp else ''
        return e.code, json.loads(raw) if raw else {'error': str(e)}


def get_access_token():
    import base64
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode('utf-8')).decode('ascii')
    req = urllib.request.Request(
        API_BASE + '/v1/oauth2/token',
        data=b'grant_type=client_credentials',
        method='POST',
    )
    req.add_header('Authorization', f'Basic {creds}')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            return body['access_token']
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8') if e.fp else ''
        _abort(f"OAuth 토큰 발급 실패 (HTTP {e.code}). 응답: {raw}\n"
               f"  → CLIENT_ID/SECRET 이 올바른지, API_BASE 가 키 환경과 맞는지(Sandbox vs Live) 확인.")


def create_product(token):
    print(f"\n[1/2] Product 생성 — '{PRODUCT_NAME}'")
    status, body = _request('POST', '/v1/catalogs/products', body={
        'name': PRODUCT_NAME,
        'description': 'AI 캐릭터와 한국어 채팅 학습 — 월 구독 무제한 이용권',
        'type': 'SERVICE',
        'category': 'ONLINE_GAMING',
    }, headers={'Authorization': f'Bearer {token}'})
    if status >= 300:
        _abort(f"Product 생성 실패 (HTTP {status}): {json.dumps(body, ensure_ascii=False, indent=2)}")
    pid = body.get('id')
    print(f"      ✓ PRODUCT_ID = {pid}")
    return pid


def create_plan(token, product_id):
    print(f"\n[2/2] Billing Plan 생성 — '{PLAN_NAME}' ${PRICE_USD}/월, trial {TRIAL_DAYS}일")
    billing_cycles = []

    if TRIAL_DAYS > 0:
        # PayPal trial = $0 의 짧은 cycle. trial_days 가 30 이하라면 'DAY' 단위로 한 cycle.
        billing_cycles.append({
            'frequency': {'interval_unit': 'DAY', 'interval_count': TRIAL_DAYS},
            'tenure_type': 'TRIAL',
            'sequence': 1,
            'total_cycles': 1,
            'pricing_scheme': {'fixed_price': {'value': '0', 'currency_code': 'USD'}},
        })

    billing_cycles.append({
        'frequency': {'interval_unit': 'MONTH', 'interval_count': 1},
        'tenure_type': 'REGULAR',
        'sequence': 2 if TRIAL_DAYS > 0 else 1,
        'total_cycles': 0,  # 0 = 무한 반복
        'pricing_scheme': {'fixed_price': {'value': PRICE_USD, 'currency_code': 'USD'}},
    })

    plan_body = {
        'product_id': product_id,
        'name': PLAN_NAME,
        'description': f'무제한 메시지 + 모든 캐릭터·시나리오·미션 액세스. 월 ${PRICE_USD}.',
        'billing_cycles': billing_cycles,
        'payment_preferences': {
            'auto_bill_outstanding': True,
            'setup_fee_failure_action': 'CONTINUE',
            'payment_failure_threshold': 3,
        },
    }
    status, body = _request('POST', '/v1/billing/plans', body=plan_body,
                            headers={'Authorization': f'Bearer {token}',
                                     'PayPal-Request-Id': f'kdate-plan-{product_id[:8]}'})
    if status >= 300:
        _abort(f"Plan 생성 실패 (HTTP {status}): {json.dumps(body, ensure_ascii=False, indent=2)}")
    plan_id = body.get('id')
    print(f"      ✓ PLAN_ID = {plan_id}  (status={body.get('status')})")
    return plan_id


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        _abort("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET 환경변수가 비어있습니다.")
    env = 'Sandbox' if 'sandbox' in API_BASE.lower() else 'Live'
    print(f"PayPal API: {API_BASE}  ({env})")
    print(f"Client ID prefix: {CLIENT_ID[:6]}...")

    print("\n[0/2] OAuth access token 발급...")
    token = get_access_token()
    print(f"      ✓ 토큰 발급 OK (앞 12자: {token[:12]}...)")

    product_id = create_product(token)
    plan_id = create_plan(token, product_id)

    print("\n" + "=" * 60)
    print("✅ 셋업 완료. 아래 값을 기록·등록하세요:")
    print("=" * 60)
    print(f"  PAYPAL_PRODUCT_ID = {product_id}    (참고용 — 환경변수 아님)")
    print(f"  PAYPAL_PLAN_ID    = {plan_id}    ← 이 값을 Secret Manager 에 등록")
    print()
    print("다음 단계 (Cloud Run 배포 후):")
    print("  1. PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_PLAN_ID 를 Secret Manager 에 추가")
    print("  2. PayPal Developer Dashboard → Webhooks → Add Webhook")
    print("     URL: https://<your-cloud-run-url>/billing/webhook")
    print("     이벤트 7개: BILLING.SUBSCRIPTION.ACTIVATED/UPDATED/CANCELLED/")
    print("                  EXPIRED/SUSPENDED/PAYMENT.FAILED, PAYMENT.SALE.COMPLETED")
    print("     발급된 Webhook ID (WH-...) → PAYPAL_WEBHOOK_ID")
    print()


if __name__ == '__main__':
    main()
