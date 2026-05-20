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

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_PRICE_ID = os.getenv('STRIPE_PRICE_ID', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:8080')

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
        session = stripe.checkout.Session.create(
            mode='subscription',
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            client_reference_id=user['user_id'],
            customer=user.get('stripe_customer_id') or None,
            customer_email=(user.get('email') if not user.get('stripe_customer_id') else None),
            success_url=f'{BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{BASE_URL}/chat?billing=canceled',
            allow_promotion_codes=True,
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
        print(f'[BILLING] webhook signature 실패: {str(e)[:100]}')
        return jsonify({'error': 'invalid signature'}), 400
    except (ValueError, AttributeError, KeyError) as e:
        # 페이로드 자체가 깨졌거나 SDK 가 예상치 못한 형태로 받는 경우.
        print(f'[BILLING] webhook payload 파싱 실패: {str(e)[:100]}')
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
                # user_id↔customer_id 만 결합. 정확한 status/period_end 는 직후 도착하는
                # customer.subscription.created 이벤트가 채운다 (Stripe 가 두 이벤트를
                # 거의 동시에 발송함). 그 사이의 짧은 race 윈도를 위해 24h grace.
                grace_end = int(time.time()) + 24 * 60 * 60
                set_subscription(
                    user_id,
                    stripe_customer_id=customer,
                    stripe_subscription_id=subscription_id,
                    status='active',
                    period_end=grace_end,
                )
                print(f'[BILLING] checkout user={user_id} customer={customer} sub={subscription_id} (24h grace)')

        elif et in ('customer.subscription.created', 'customer.subscription.updated'):
            customer = obj.get('customer')
            user = get_user_by_stripe_customer(customer) if customer else None
            if user:
                set_subscription(
                    user['user_id'],
                    stripe_customer_id=customer,
                    stripe_subscription_id=obj.get('id'),
                    status=obj.get('status'),
                    period_end=int(obj.get('current_period_end') or 0),
                )
                print(f'[BILLING] subscription {et.split(".")[-1]} user={user["user_id"]} status={obj.get("status")}')

        elif et == 'customer.subscription.deleted':
            customer = obj.get('customer')
            user = get_user_by_stripe_customer(customer) if customer else None
            if user:
                clear_subscription(user['user_id'])
                print(f'[BILLING] canceled user={user["user_id"]}')

    except Exception as e:
        # 핸들러 에러는 로깅만 — Stripe 재시도 무한루프 방지 위해 200 반환
        print(f'[BILLING] webhook handler error ({et}): {str(e)[:200]}')

    return jsonify({'received': True}), 200
