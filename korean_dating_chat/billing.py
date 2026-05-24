"""Stripe Checkout (subscription mode) + webhook + customer portal.

ENV:
  STRIPE_SECRET_KEY        — sk_test_... / sk_live_...
  STRIPE_PRICE_ID          — Stripe dashboard 에서 미리 만든 월 구독 Price ID (price_...)
  STRIPE_WEBHOOK_SECRET    — Stripe CLI / dashboard 에서 발급
  APP_BASE_URL             — success/cancel URL 조립용

웹훅 이벤트 처리:
  checkout.session.completed         → set_subscription(active, period_end)
  customer.subscription.updated      → status/period_end 동기화
  customer.subscription.deleted      → clear_subscription
"""
import json
import os
import time

import stripe
from flask import request, jsonify, redirect

from users import (
    get_user_by_stripe_customer,
    set_subscription,
    clear_subscription,
)
from auth import current_user
from events import log_event

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_PRICE_ID = os.getenv('STRIPE_PRICE_ID', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:8080')

# Trial 일수. 0 = trial 비활성 (즉시 결제). 7~14가 일반적.
# Stripe 가 동일 customer 의 중복 trial 을 막아주므로 abuse 방지는 자동.
TRIAL_DAYS = int(os.getenv('STRIPE_TRIAL_DAYS', '7') or '0')

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def stripe_enabled():
    return bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)


# ---- Checkout / Portal -------------------------------------------------------

def create_checkout_session():
    user = current_user()
    if not user:
        return jsonify({'error': '로그인이 필요해요.'}), 401
    if not stripe_enabled():
        # 결제가 아직 설정 안 됨 — 클라이언트는 '결제 준비 중' 안내
        return jsonify({'error': '결제가 준비 중이에요. 잠시 후 다시 시도해주세요.'}), 503
    try:
        # subscription_data 에 trial_period_days 를 넣으면 첫 결제가 trial 종료 시점으로 미뤄짐.
        # Stripe 가 같은 customer 의 중복 trial 을 자동 차단 — 첫 구독자만 trial 받음.
        sub_data = {}
        if TRIAL_DAYS > 0:
            sub_data['trial_period_days'] = TRIAL_DAYS
        session = stripe.checkout.Session.create(
            mode='subscription',
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            client_reference_id=user['user_id'],
            customer=user.get('stripe_customer_id') or None,
            customer_email=(user.get('email') if not user.get('stripe_customer_id') else None),
            success_url=f'{BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{BASE_URL}/chat?billing=canceled',
            allow_promotion_codes=True,
            subscription_data=sub_data or None,
        )
        return jsonify({'url': session.url})
    except stripe.error.StripeError as e:
        print(f'[BILLING] checkout create failed: {str(e)[:200]}')
        return jsonify({'error': '결제 세션을 만들 수 없어요. 잠시 후 다시 시도해주세요.'}), 502


def create_portal_session():
    user = current_user()
    if not user:
        return jsonify({'error': '로그인이 필요해요.'}), 401
    if not user.get('stripe_customer_id'):
        return jsonify({'error': '구독 정보가 없어요.'}), 400
    if not stripe_enabled():
        return jsonify({'error': '결제가 비활성 상태예요.'}), 503
    try:
        portal = stripe.billing_portal.Session.create(
            customer=user['stripe_customer_id'],
            return_url=f'{BASE_URL}/chat',
        )
        return jsonify({'url': portal.url})
    except stripe.error.StripeError as e:
        print(f'[BILLING] portal failed: {str(e)[:200]}')
        return jsonify({'error': '관리 페이지를 열 수 없어요.'}), 502


def billing_success():
    return redirect('/chat?billing=success')


def cancel_user_subscription(user):
    """사용자 행에 연결된 Stripe 구독을 cancel_at_period_end=True 로 표시.

    즉시 해지 X — 결제 주기 끝에 해지. 사용자가 낸 돈만큼은 쓸 수 있게.
    Stripe webhook(customer.subscription.updated)이 곧 도착해 DB 동기화.
    """
    if not user or not user.get('stripe_subscription_id'):
        return (True, None)
    if not stripe_enabled():
        # 로컬·테스트: API 호출 불가. DB 만 표시 + 이벤트 직접 기록.
        from users import set_subscription
        set_subscription(
            user['user_id'],
            stripe_customer_id=user.get('stripe_customer_id'),
            stripe_subscription_id=user.get('stripe_subscription_id'),
            status=user.get('subscription_status') or 'canceled',
            period_end=user.get('subscription_period_end') or 0,
            cancel_at_period_end=True,
        )
        log_event('warn', 'subscription.cancel_scheduled',
                  message=f'user={user["user_id"]} (local, no Stripe)',
                  user_id=user['user_id'])
        return (True, None)
    try:
        stripe.Subscription.modify(
            user['stripe_subscription_id'],
            cancel_at_period_end=True,
        )
        # Stripe → webhook → set_subscription + log_event 자동
        return (True, None)
    except stripe.error.StripeError as e:
        log_event('error', 'subscription.cancel_failed',
                  message=str(e)[:200], user_id=user.get('user_id'))
        return (False, '구독 해지에 실패했어요. 잠시 후 다시 시도해주세요.')


# ---- Webhook -----------------------------------------------------------------

def webhook():
    """Stripe webhook 핸들러. 항상 200 반환 (Stripe 재시도 폭주 방지).

    필수: STRIPE_WEBHOOK_SECRET. 서명 검증 실패 시에만 400 반환 (재시도 OK).
    """
    payload = request.get_data()
    sig = request.headers.get('Stripe-Signature', '')
    if not STRIPE_WEBHOOK_SECRET:
        print('[BILLING] webhook secret 미설정 — 이벤트 무시')
        return jsonify({'error': 'webhook not configured'}), 503
    try:
        # 서명 검증만. 반환되는 StripeObject 는 dict 인터페이스가 일부 빠져있어
        # 우리는 원본 페이로드를 다시 dict 로 파싱해서 사용.
        stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError as e:
        # critical — 서명 위조는 공격 가능성. 즉시 모니터링 필요.
        log_event('critical', 'webhook.signature_invalid',
                  message='Stripe webhook signature 검증 실패',
                  remote_addr=request.remote_addr, err=str(e)[:120])
        return jsonify({'error': 'invalid signature'}), 400
    except (ValueError, AttributeError, KeyError) as e:
        # 페이로드 자체가 깨졌거나 SDK 가 예상치 못한 형태로 받는 경우.
        log_event('error', 'webhook.payload_invalid',
                  message=f'페이로드 파싱 실패: {str(e)[:120]}',
                  remote_addr=request.remote_addr)
        return jsonify({'error': 'invalid payload'}), 400

    try:
        event = json.loads(payload)
    except (ValueError, TypeError):
        return jsonify({'error': 'invalid json'}), 400
    et = event.get('type', '') if isinstance(event, dict) else ''
    obj = (event.get('data') or {}).get('object') or {} if isinstance(event, dict) else {}

    try:
        if et == 'checkout.session.completed':
            user_id = obj.get('client_reference_id')
            customer = obj.get('customer')
            subscription_id = obj.get('subscription')
            if user_id and customer:
                grace_end = int(time.time()) + 24 * 60 * 60
                set_subscription(
                    user_id,
                    stripe_customer_id=customer,
                    stripe_subscription_id=subscription_id,
                    status='active',
                    period_end=grace_end,
                )
                log_event('info', 'subscription.checkout_completed',
                          message=f'user={user_id} sub={subscription_id} (24h grace)',
                          user_id=user_id, customer_id=customer, subscription_id=subscription_id)

        elif et in ('customer.subscription.created', 'customer.subscription.updated'):
            customer = obj.get('customer')
            user = get_user_by_stripe_customer(customer) if customer else None
            if user:
                prev_status = user.get('subscription_status')
                prev_cancel = bool(user.get('subscription_cancel_at_period_end'))
                new_status = obj.get('status')
                new_cancel = bool(obj.get('cancel_at_period_end'))
                set_subscription(
                    user['user_id'],
                    stripe_customer_id=customer,
                    stripe_subscription_id=obj.get('id'),
                    status=new_status,
                    period_end=int(obj.get('current_period_end') or 0),
                    cancel_at_period_end=new_cancel,
                )
                # 상태 전환별 이벤트
                if new_status == 'trialing' and prev_status != 'trialing':
                    log_event('info', 'subscription.trial_started',
                              message=f'user={user["user_id"]}',
                              user_id=user['user_id'])
                elif new_status == 'active' and prev_status != 'active':
                    log_event('info', 'subscription.activated',
                              message=f'user={user["user_id"]} (from {prev_status})',
                              user_id=user['user_id'], prev_status=prev_status)
                elif new_status == 'past_due' and prev_status != 'past_due':
                    log_event('warn', 'subscription.past_due',
                              message=f'user={user["user_id"]} payment retry in progress',
                              user_id=user['user_id'])
                if new_cancel and not prev_cancel:
                    log_event('warn', 'subscription.cancel_scheduled',
                              message=f'user={user["user_id"]} period_end={obj.get("current_period_end")}',
                              user_id=user['user_id'], period_end=obj.get('current_period_end'))

        elif et == 'customer.subscription.deleted':
            customer = obj.get('customer')
            user = get_user_by_stripe_customer(customer) if customer else None
            if user:
                clear_subscription(user['user_id'])
                log_event('warn', 'subscription.canceled',
                          message=f'user={user["user_id"]} fully canceled',
                          user_id=user['user_id'])

        elif et == 'customer.subscription.trial_will_end':
            customer = obj.get('customer')
            user = get_user_by_stripe_customer(customer) if customer else None
            if user:
                log_event('info', 'subscription.trial_will_end',
                          message=f'user={user["user_id"]} trial ending soon',
                          user_id=user['user_id'], trial_end=obj.get('trial_end'))

        elif et == 'invoice.payment_failed':
            # 결제 실패 — past_due 진입 전후로 Stripe 가 발송. 운영자 알림 필요.
            customer = obj.get('customer')
            user = get_user_by_stripe_customer(customer) if customer else None
            attempt = obj.get('attempt_count') or 1
            log_event('warn' if attempt < 3 else 'critical', 'payment.failed',
                      message=f'invoice payment failed attempt={attempt}',
                      user_id=(user or {}).get('user_id'),
                      customer_id=customer,
                      attempt_count=attempt,
                      amount=obj.get('amount_due'))

        elif et == 'invoice.payment_succeeded':
            # 첫 결제·갱신 성공 로그 (info, MRR 추적용)
            customer = obj.get('customer')
            user = get_user_by_stripe_customer(customer) if customer else None
            log_event('info', 'payment.succeeded',
                      message=f'invoice paid',
                      user_id=(user or {}).get('user_id'),
                      customer_id=customer,
                      amount=obj.get('amount_paid'))

    except Exception as e:
        # 핸들러 에러는 로깅만 — Stripe 재시도 무한루프 방지 위해 200 반환
        print(f'[BILLING] webhook handler error ({et}): {str(e)[:200]}')

    return jsonify({'received': True}), 200
