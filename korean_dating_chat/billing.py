"""PayPal Subscriptions API 결제 통합.

PayPal Business 계정 + Developer 앱 + Billing Plan + Webhook 가 사전 셋업돼 있어야 함.
자세한 단계는 docs/BILLING_SETUP.md.

ENV (모두 필수, sandbox/live 분기):
  PAYPAL_CLIENT_ID         앱의 Client ID
  PAYPAL_CLIENT_SECRET     앱의 Secret
  PAYPAL_PLAN_ID           월 구독 Billing Plan ID (P-XXX)
  PAYPAL_WEBHOOK_ID        Webhook ID (WH-XXX, 서명 검증용)
  PAYPAL_API_BASE          'https://api-m.sandbox.paypal.com' (test) | 'https://api-m.paypal.com' (live)
  APP_BASE_URL             redirect URL 조립

ENV (선택, 테스트):
  PAYPAL_WEBHOOK_TEST_BYPASS=1   서명 검증 우회. 시뮬레이터 사용 시.

Webhook 이벤트 → 우리 정규화 이벤트 매핑:
  BILLING.SUBSCRIPTION.ACTIVATED       → subscription.activated
  BILLING.SUBSCRIPTION.UPDATED         → subscription.updated
  BILLING.SUBSCRIPTION.RE-ACTIVATED    → subscription.activated
  BILLING.SUBSCRIPTION.CANCELLED       → subscription.cancel_scheduled (period_end 까지 grace)
  BILLING.SUBSCRIPTION.EXPIRED         → subscription.canceled (즉시 만료)
  BILLING.SUBSCRIPTION.SUSPENDED       → subscription.past_due
  BILLING.SUBSCRIPTION.PAYMENT.FAILED  → payment.failed
  PAYMENT.SALE.COMPLETED               → payment.succeeded
"""
import json
import os
import time
from datetime import datetime, timezone

import requests
from flask import request, jsonify, redirect

from users import (
    get_user_by_subscription_id,
    get_user_by_subscription_customer,
    set_subscription,
    clear_subscription,
)
from auth import current_user
from events import log_event


PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', '')
PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', '')
PAYPAL_PLAN_ID = os.getenv('PAYPAL_PLAN_ID', '')
PAYPAL_WEBHOOK_ID = os.getenv('PAYPAL_WEBHOOK_ID', '')
PAYPAL_API_BASE = os.getenv('PAYPAL_API_BASE', 'https://api-m.sandbox.paypal.com').rstrip('/')

BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:8080').rstrip('/')

# 무료 체험 일수. PayPal Billing Plan 의 trial phase 에서 실제 적용됨 — 이 값은 표시·통계용.
TRIAL_DAYS = int(os.getenv('PAYPAL_TRIAL_DAYS', '7') or '7')

# 시뮬레이터 통합 테스트용 — 서명 검증 우회. 운영에서는 반드시 미설정.
_WEBHOOK_TEST_BYPASS = os.getenv('PAYPAL_WEBHOOK_TEST_BYPASS') == '1'


# ---- 접근 토큰 캐시 ---------------------------------------------------------
# PayPal access_token 은 보통 ~8h 유효. 만료 1분 전부터 재발급.
_TOKEN_CACHE = {'token': None, 'expires_at': 0}


def _get_access_token():
    now = time.time()
    if _TOKEN_CACHE['token'] and _TOKEN_CACHE['expires_at'] > now + 60:
        return _TOKEN_CACHE['token']
    if not (PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET):
        raise RuntimeError('PAYPAL credentials not configured')
    resp = requests.post(
        f'{PAYPAL_API_BASE}/v1/oauth2/token',
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        data={'grant_type': 'client_credentials'},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _TOKEN_CACHE['token'] = data['access_token']
    _TOKEN_CACHE['expires_at'] = now + int(data.get('expires_in', 3600))
    return _TOKEN_CACHE['token']


def paypal_enabled():
    return bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET and PAYPAL_PLAN_ID)


def billing_enabled():
    return paypal_enabled()


# ---- 시간 유틸 --------------------------------------------------------------

def _parse_paypal_time(t):
    """PayPal ISO 8601 timestamp (예: '2026-06-01T10:00:00Z') → unix seconds."""
    if not t:
        return None
    try:
        return int(datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp())
    except (ValueError, TypeError):
        return None


# ---- Checkout (구독 생성 → approval URL 발급) ------------------------------

def create_checkout_session():
    user = current_user()
    if not user:
        return jsonify({'error': '로그인이 필요해요.'}), 401
    if not paypal_enabled():
        return jsonify({'error': '결제가 준비 중이에요. 잠시 후 다시 시도해주세요.'}), 503
    try:
        token = _get_access_token()
        payload = {
            'plan_id': PAYPAL_PLAN_ID,
            # custom_id 에 우리 user_id 를 실어두면 webhook 에서 매핑 가능 (Stripe 의 client_reference_id 대응)
            'custom_id': user['user_id'],
            'application_context': {
                'brand_name': 'K-Dating Chat',
                'user_action': 'SUBSCRIBE_NOW',
                'shipping_preference': 'NO_SHIPPING',
                'return_url': f'{BASE_URL}/billing/success',
                'cancel_url': f'{BASE_URL}/chat?billing=canceled',
            },
        }
        if user.get('email'):
            payload['subscriber'] = {'email_address': user['email']}
        r = requests.post(
            f'{PAYPAL_API_BASE}/v1/billing/subscriptions',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Prefer': 'return=representation',
            },
            json=payload,
            timeout=15,
        )
        if r.status_code not in (200, 201):
            print(f'[BILLING] PayPal checkout failed {r.status_code}: {r.text[:300]}')
            log_event('error', 'paypal.checkout_failed',
                      message=f'status={r.status_code}', user_id=user['user_id'])
            return jsonify({'error': '결제 세션을 만들 수 없어요. 잠시 후 다시 시도해주세요.'}), 502
        sub = r.json()
        approval = next(
            (l['href'] for l in sub.get('links', []) if l.get('rel') == 'approve'),
            None,
        )
        if not approval:
            return jsonify({'error': '승인 URL 을 받지 못했어요.'}), 502
        # subscription_id 는 webhook 이 마무리 (사용자가 approve 해야 active)
        return jsonify({'url': approval, 'subscription_id': sub.get('id')})
    except (requests.RequestException, RuntimeError) as e:
        print(f'[BILLING] PayPal API error: {str(e)[:200]}')
        log_event('error', 'paypal.api_error', message=str(e)[:200])
        return jsonify({'error': '결제 서비스 연결에 실패했어요.'}), 502


def billing_success():
    """PayPal 승인 후 사용자가 돌아오는 곳. ?subscription_id=I-XXX 포함됨."""
    return redirect('/chat?billing=success')


# ---- 사용자 직접 해지 -------------------------------------------------------

def cancel_user_subscription(user):
    """사용자의 PayPal 구독 cancel API 호출.

    PayPal cancel = subscription.status → 'CANCELLED' 즉시. 하지만 webhook 핸들러가
    period_end 까지는 cancel_at_period_end=true grace 로 처리하여 사용자가 낸 돈 만큼은 사용 가능.
    """
    if not user or not user.get('subscription_id'):
        return (True, None)
    if not paypal_enabled():
        # 로컬·테스트 환경 — DB 만 표시. 시뮬레이터가 webhook 이벤트 흉내 가능.
        set_subscription(
            user['user_id'],
            payment_provider=user.get('payment_provider') or 'paypal',
            subscription_customer_id=user.get('subscription_customer_id'),
            subscription_id=user.get('subscription_id'),
            status=user.get('subscription_status') or 'active',
            period_end=user.get('subscription_period_end') or 0,
            cancel_at_period_end=True,
        )
        log_event('warn', 'subscription.cancel_scheduled',
                  message=f'user={user["user_id"]} (local, no PayPal)',
                  user_id=user['user_id'])
        return (True, None)
    try:
        token = _get_access_token()
        r = requests.post(
            f'{PAYPAL_API_BASE}/v1/billing/subscriptions/{user["subscription_id"]}/cancel',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json={'reason': 'User requested cancellation'},
            timeout=15,
        )
        if r.status_code not in (200, 204):
            print(f'[BILLING] PayPal cancel failed {r.status_code}: {r.text[:200]}')
            log_event('error', 'subscription.cancel_failed',
                      message=r.text[:200], user_id=user.get('user_id'))
            return (False, '구독 해지에 실패했어요. 잠시 후 다시 시도해주세요.')
        # webhook BILLING.SUBSCRIPTION.CANCELLED 이 곧 도착 → 우리 DB 동기화
        return (True, None)
    except (requests.RequestException, RuntimeError) as e:
        log_event('error', 'subscription.cancel_failed', message=str(e)[:200])
        return (False, '결제 서비스 연결 실패')


# ---- "Customer portal" — PayPal 은 별도 portal 없음 -------------------------

def create_portal_session():
    """PayPal은 Stripe 같은 customer portal 없음 — 사용자의 PayPal 자체 자동결제 페이지로 안내."""
    user = current_user()
    if not user:
        return jsonify({'error': '로그인이 필요해요.'}), 401
    # 모든 사용자 동일 URL — PayPal 로그인하면 본인 자동 결제 목록 표시.
    return jsonify({'url': 'https://www.paypal.com/myaccount/autopay/'})


# ---- Webhook ---------------------------------------------------------------

def _verify_webhook(headers, body):
    """PayPal webhook 서명 검증.

    PayPal 의 서명 검증은 API roundtrip 방식 — 헤더 + 페이로드 + WEBHOOK_ID 를
    PayPal 에 보내 'SUCCESS' / 'FAILURE' 응답 받음. Stripe 의 HMAC 보다 약간 무거움.
    """
    if not PAYPAL_WEBHOOK_ID:
        return False
    try:
        event = json.loads(body)
    except (ValueError, TypeError):
        return False
    try:
        token = _get_access_token()
        r = requests.post(
            f'{PAYPAL_API_BASE}/v1/notifications/verify-webhook-signature',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json={
                'auth_algo':         headers.get('Paypal-Auth-Algo', ''),
                'cert_url':          headers.get('Paypal-Cert-Url', ''),
                'transmission_id':   headers.get('Paypal-Transmission-Id', ''),
                'transmission_sig':  headers.get('Paypal-Transmission-Sig', ''),
                'transmission_time': headers.get('Paypal-Transmission-Time', ''),
                'webhook_id': PAYPAL_WEBHOOK_ID,
                'webhook_event': event,
            },
            timeout=10,
        )
        return r.status_code == 200 and r.json().get('verification_status') == 'SUCCESS'
    except (requests.RequestException, RuntimeError, ValueError, KeyError):
        return False


def _handle_subscription_activated(resource):
    """BILLING.SUBSCRIPTION.ACTIVATED 또는 RE-ACTIVATED."""
    sub_id = resource.get('id')
    custom_id = resource.get('custom_id')  # 우리 user_id (checkout 시 심어둠)
    subscriber = resource.get('subscriber') or {}
    payer_id = subscriber.get('payer_id') or subscriber.get('email_address')
    billing = resource.get('billing_info') or {}
    period_end = _parse_paypal_time(billing.get('next_billing_time')) or 0

    # custom_id 없으면 (이미 등록된 sub_id 로 다시 들어온 경우) sub_id 로 조회
    user_id = custom_id
    if not user_id and sub_id:
        u = get_user_by_subscription_id(sub_id)
        user_id = (u or {}).get('user_id')
    if not (user_id and sub_id):
        return
    set_subscription(
        user_id,
        payment_provider='paypal',
        subscription_customer_id=payer_id,
        subscription_id=sub_id,
        status='active',
        period_end=period_end or (int(time.time()) + 30 * 86400),  # period_end 없으면 30일 grace
    )
    log_event('info', 'subscription.activated',
              message=f'user={user_id} sub={sub_id}', user_id=user_id)


def _handle_subscription_updated(resource):
    sub_id = resource.get('id')
    if not sub_id:
        return
    user = get_user_by_subscription_id(sub_id)
    if not user:
        return
    billing = resource.get('billing_info') or {}
    period_end = _parse_paypal_time(billing.get('next_billing_time')) or 0
    status = (resource.get('status') or '').lower()
    if status == 'cancelled':
        status = 'canceled'   # 정규화
    set_subscription(
        user['user_id'],
        payment_provider='paypal',
        subscription_customer_id=user.get('subscription_customer_id'),
        subscription_id=sub_id,
        status=status or 'active',
        period_end=period_end or user.get('subscription_period_end') or 0,
    )


def _handle_subscription_cancelled(resource):
    """PayPal CANCELLED = 즉시 cancel API 결과. 다만 우리는 period_end 까지 grace 처리."""
    sub_id = resource.get('id')
    if not sub_id:
        return
    user = get_user_by_subscription_id(sub_id)
    if not user:
        return
    billing = resource.get('billing_info') or {}
    period_end = (
        _parse_paypal_time(billing.get('next_billing_time'))
        or user.get('subscription_period_end')
        or 0
    )
    set_subscription(
        user['user_id'],
        payment_provider='paypal',
        subscription_customer_id=user.get('subscription_customer_id'),
        subscription_id=sub_id,
        status='canceled',
        period_end=period_end,
        cancel_at_period_end=True,
    )
    log_event('warn', 'subscription.cancel_scheduled',
              message=f'user={user["user_id"]} sub={sub_id}',
              user_id=user['user_id'])


def _handle_subscription_expired(resource):
    sub_id = resource.get('id')
    if not sub_id:
        return
    user = get_user_by_subscription_id(sub_id)
    if not user:
        return
    clear_subscription(user['user_id'])
    log_event('warn', 'subscription.canceled',
              message=f'user={user["user_id"]} expired', user_id=user['user_id'])


def _handle_subscription_suspended(resource):
    sub_id = resource.get('id')
    if not sub_id:
        return
    user = get_user_by_subscription_id(sub_id)
    if not user:
        return
    set_subscription(
        user['user_id'],
        payment_provider='paypal',
        subscription_customer_id=user.get('subscription_customer_id'),
        subscription_id=sub_id,
        status='past_due',
        period_end=user.get('subscription_period_end') or 0,
    )
    log_event('warn', 'subscription.past_due',
              message=f'user={user["user_id"]}', user_id=user['user_id'])


def _handle_payment_failed(resource):
    sub_id = resource.get('id')
    user = get_user_by_subscription_id(sub_id) if sub_id else None
    failures = (resource.get('billing_info') or {}).get('failed_payments_count', 1)
    severity = 'critical' if failures >= 3 else 'warn'
    log_event(severity, 'payment.failed',
              message=f'sub={sub_id} attempt={failures}',
              user_id=(user or {}).get('user_id'),
              attempt_count=failures)


def _handle_payment_succeeded(resource):
    # PAYMENT.SALE.COMPLETED resource shape: billing_agreement_id, amount{total}
    sub_id = resource.get('billing_agreement_id')
    user = get_user_by_subscription_id(sub_id) if sub_id else None
    amount = (resource.get('amount') or {}).get('total')
    log_event('info', 'payment.succeeded',
              message=f'sub={sub_id} amount={amount}',
              user_id=(user or {}).get('user_id'),
              amount=amount, sub_id=sub_id)


# 이벤트 dispatch 테이블
_HANDLERS = {
    'BILLING.SUBSCRIPTION.ACTIVATED':       _handle_subscription_activated,
    'BILLING.SUBSCRIPTION.RE-ACTIVATED':    _handle_subscription_activated,
    'BILLING.SUBSCRIPTION.UPDATED':         _handle_subscription_updated,
    'BILLING.SUBSCRIPTION.CANCELLED':       _handle_subscription_cancelled,
    'BILLING.SUBSCRIPTION.EXPIRED':         _handle_subscription_expired,
    'BILLING.SUBSCRIPTION.SUSPENDED':       _handle_subscription_suspended,
    'BILLING.SUBSCRIPTION.PAYMENT.FAILED':  _handle_payment_failed,
    'PAYMENT.SALE.COMPLETED':               _handle_payment_succeeded,
}


def webhook():
    """PayPal webhook 핸들러. PayPal-Transmission-* 헤더 + WEBHOOK_ID 로 서명 검증."""
    payload = request.get_data()

    if not _WEBHOOK_TEST_BYPASS:
        if not PAYPAL_WEBHOOK_ID:
            print('[BILLING] PAYPAL_WEBHOOK_ID 미설정 — 이벤트 무시')
            return jsonify({'error': 'webhook not configured'}), 503
        if not _verify_webhook(request.headers, payload):
            log_event('critical', 'webhook.signature_invalid',
                      message='PayPal webhook signature 검증 실패',
                      remote_addr=request.remote_addr)
            return jsonify({'error': 'invalid signature'}), 400

    try:
        event = json.loads(payload)
    except (ValueError, TypeError):
        return jsonify({'error': 'invalid json'}), 400

    et = event.get('event_type', '') if isinstance(event, dict) else ''
    resource = event.get('resource', {}) if isinstance(event, dict) else {}

    handler = _HANDLERS.get(et)
    if handler:
        try:
            handler(resource)
        except Exception as e:
            print(f'[BILLING] webhook handler error ({et}): {str(e)[:200]}')
            log_event('error', 'webhook.handler_error',
                      message=f'{et}: {str(e)[:160]}')
    # else: ignore unknown events (정상 — 우리가 등록 안 한 PayPal 이벤트가 가끔 옴)

    return jsonify({'received': True}), 200
