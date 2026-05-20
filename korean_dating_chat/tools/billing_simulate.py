"""Stripe webhook 시뮬레이터.

실 Stripe 계정 없이도 로컬에서 결제 flow 검증용. STRIPE_WEBHOOK_SECRET 만 설정돼 있으면
Stripe 의 서명 규약(t=...,v1=HMAC) 그대로 만들어 /billing/webhook 에 POST 한다.

사용 예:
  # checkout.session.completed
  python3 tools/billing_simulate.py checkout \\
      --user-id USR123 --customer cus_test_123 --subscription sub_test_456

  # customer.subscription.updated (active, period_end 30일 뒤)
  python3 tools/billing_simulate.py sub-update \\
      --customer cus_test_123 --subscription sub_test_456 --status active --days 30

  # customer.subscription.deleted
  python3 tools/billing_simulate.py sub-delete \\
      --customer cus_test_123 --subscription sub_test_456

서명 검증을 통과시키려면 시뮬레이터와 서버가 같은 STRIPE_WEBHOOK_SECRET 을 봐야 함.
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request


def _sign(payload_bytes, secret, ts=None):
    """Stripe webhook 서명 헤더(Stripe-Signature) 값을 만든다.

    포맷: t=<unix_ts>,v1=<HEX(HMAC-SHA256(secret, "{ts}.{payload}"))>
    """
    ts = ts if ts is not None else int(time.time())
    signed_payload = f'{ts}.'.encode() + payload_bytes
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f't={ts},v1={sig}'


def _post(url, body, sig):
    req = urllib.request.Request(
        url,
        data=body,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Stripe-Signature': sig,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')


def _event(event_type, data_object):
    """Stripe event 페이로드 형식. `object: "event"` 가 반드시 있어야 SDK 가 받아준다."""
    return {
        'id': f'evt_test_{int(time.time() * 1000)}',
        'object': 'event',
        'type': event_type,
        'api_version': '2024-04-10',
        'created': int(time.time()),
        'data': {'object': data_object},
        'livemode': False,
    }


def cmd_checkout(args, secret, url):
    obj = {
        'object': 'checkout.session',
        'id': f'cs_test_{int(time.time())}',
        'client_reference_id': args.user_id,
        'customer': args.customer,
        'subscription': args.subscription,
        'mode': 'subscription',
        'payment_status': 'paid',
    }
    return _send_event('checkout.session.completed', obj, secret, url)


def cmd_sub_update(args, secret, url):
    period_end = int(time.time()) + args.days * 24 * 60 * 60
    obj = {
        'object': 'subscription',
        'id': args.subscription,
        'customer': args.customer,
        'status': args.status,
        'current_period_end': period_end,
        'cancel_at_period_end': False,
    }
    et = 'customer.subscription.created' if args.created else 'customer.subscription.updated'
    return _send_event(et, obj, secret, url)


def cmd_sub_delete(args, secret, url):
    obj = {
        'object': 'subscription',
        'id': args.subscription,
        'customer': args.customer,
        'status': 'canceled',
        'current_period_end': int(time.time()),
    }
    return _send_event('customer.subscription.deleted', obj, secret, url)


def _send_event(event_type, data_object, secret, url):
    body = json.dumps(_event(event_type, data_object)).encode()
    sig = _sign(body, secret)
    status, text = _post(url, body, sig)
    print(f'[simulate] {event_type} → {status}')
    if text:
        print(f'  {text[:300]}')
    return status == 200


def main():
    p = argparse.ArgumentParser(description='Stripe webhook 시뮬레이터')
    p.add_argument('--url', default=os.getenv('WEBHOOK_URL', 'http://127.0.0.1:8080/billing/webhook'))
    p.add_argument('--secret', default=os.getenv('STRIPE_WEBHOOK_SECRET'),
                   help='webhook 서명 비밀키 (또는 환경변수)')

    sub = p.add_subparsers(dest='cmd', required=True)

    c = sub.add_parser('checkout', help='checkout.session.completed')
    c.add_argument('--user-id', required=True)
    c.add_argument('--customer', required=True)
    c.add_argument('--subscription', required=True)
    c.set_defaults(func=cmd_checkout)

    u = sub.add_parser('sub-update', help='customer.subscription.updated')
    u.add_argument('--customer', required=True)
    u.add_argument('--subscription', required=True)
    u.add_argument('--status', default='active', choices=['active', 'trialing', 'past_due', 'canceled', 'incomplete'])
    u.add_argument('--days', type=int, default=30, help='period_end 까지 일수')
    u.add_argument('--created', action='store_true', help='created 이벤트로 발송')
    u.set_defaults(func=cmd_sub_update)

    d = sub.add_parser('sub-delete', help='customer.subscription.deleted')
    d.add_argument('--customer', required=True)
    d.add_argument('--subscription', required=True)
    d.set_defaults(func=cmd_sub_delete)

    args = p.parse_args()
    if not args.secret:
        print('ERROR: STRIPE_WEBHOOK_SECRET 환경변수 또는 --secret 필요', file=sys.stderr)
        sys.exit(2)
    ok = args.func(args, args.secret, args.url)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
