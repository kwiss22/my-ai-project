"""PayPal webhook 시뮬레이터 (통합 테스트용).

실 PayPal 계정 없이 결제 lifecycle 검증. 서명 검증은 PAYPAL_WEBHOOK_TEST_BYPASS=1
서버에서만 우회 가능 — 운영에선 미설정.

사용 예:
  python3 tools/billing_simulate.py activate \\
      --user-id USR123 --subscription I-TEST123 --payer-id ABC123 --days 30

  python3 tools/billing_simulate.py update \\
      --subscription I-TEST123 --status ACTIVE --days 30

  python3 tools/billing_simulate.py cancel \\
      --subscription I-TEST123

  python3 tools/billing_simulate.py expire \\
      --subscription I-TEST123

  python3 tools/billing_simulate.py suspend \\
      --subscription I-TEST123

  python3 tools/billing_simulate.py payment-failed \\
      --subscription I-TEST123 --attempt 3

  python3 tools/billing_simulate.py payment-succeeded \\
      --subscription I-TEST123 --amount 4.99

각 명령은 PayPal 의 실제 이벤트 페이로드 모양을 흉내내서 /billing/webhook 에 POST.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta


def _post(url, body):
    """서명 헤더 없이 POST. 서버는 PAYPAL_WEBHOOK_TEST_BYPASS=1 일 때만 받음."""
    req = urllib.request.Request(
        url, data=body, method='POST',
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')


def _event(event_type, resource):
    """PayPal webhook event 페이로드 형식."""
    now = datetime.now(timezone.utc)
    return {
        'id':                  f'WH-TEST-{int(time.time() * 1000)}',
        'event_version':       '1.0',
        'create_time':         now.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        'resource_type':       'subscription' if 'SUBSCRIPTION' in event_type else 'sale',
        'event_type':          event_type,
        'summary':             f'test event {event_type}',
        'resource':            resource,
    }


def _iso_in(days):
    """N일 뒤 ISO 8601 (PayPal 형식)."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')


def _send(event_type, resource, url):
    body = json.dumps(_event(event_type, resource)).encode()
    status, text = _post(url, body)
    print(f'[simulate] {event_type} → {status}')
    if text:
        print(f'  {text[:300]}')
    return status == 200


def cmd_activate(args, url):
    return _send('BILLING.SUBSCRIPTION.ACTIVATED', {
        'id':           args.subscription,
        'plan_id':      'P-TEST-PLAN',
        'status':       'ACTIVE',
        'custom_id':    args.user_id,
        'subscriber': {
            'payer_id':       args.payer_id,
            'email_address':  args.email or 'test@example.com',
        },
        'billing_info': {
            'next_billing_time': _iso_in(args.days),
            'failed_payments_count': 0,
        },
    }, url)


def cmd_update(args, url):
    return _send('BILLING.SUBSCRIPTION.UPDATED', {
        'id':         args.subscription,
        'status':     args.status,
        'billing_info': {
            'next_billing_time': _iso_in(args.days),
        },
    }, url)


def cmd_cancel(args, url):
    """사용자가 cancel — PayPal CANCELLED. period_end 미래라 우리는 grace."""
    return _send('BILLING.SUBSCRIPTION.CANCELLED', {
        'id':     args.subscription,
        'status': 'CANCELLED',
        'billing_info': {
            'next_billing_time': _iso_in(args.days),
        },
    }, url)


def cmd_expire(args, url):
    """주기 끝나 완전 만료."""
    return _send('BILLING.SUBSCRIPTION.EXPIRED', {
        'id':     args.subscription,
        'status': 'EXPIRED',
    }, url)


def cmd_suspend(args, url):
    """결제 실패로 suspend (past_due)."""
    return _send('BILLING.SUBSCRIPTION.SUSPENDED', {
        'id':     args.subscription,
        'status': 'SUSPENDED',
    }, url)


def cmd_payment_failed(args, url):
    return _send('BILLING.SUBSCRIPTION.PAYMENT.FAILED', {
        'id':     args.subscription,
        'billing_info': {
            'failed_payments_count': args.attempt,
        },
    }, url)


def cmd_payment_succeeded(args, url):
    return _send('PAYMENT.SALE.COMPLETED', {
        'id':                    f'PAY-{int(time.time())}',
        'billing_agreement_id':  args.subscription,
        'amount': {
            'total':    f'{args.amount:.2f}',
            'currency': args.currency,
        },
    }, url)


def main():
    p = argparse.ArgumentParser(description='PayPal webhook 시뮬레이터')
    p.add_argument('--url',
                   default=os.getenv('WEBHOOK_URL', 'http://127.0.0.1:8080/billing/webhook'))
    sub = p.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('activate', help='BILLING.SUBSCRIPTION.ACTIVATED')
    a.add_argument('--user-id', required=True, help='우리 user_id (custom_id 로 PayPal 에 전달된 값)')
    a.add_argument('--subscription', required=True, help='PayPal subscription ID (I-XXX)')
    a.add_argument('--payer-id', default='PAYER-TEST', help='PayPal payer_id')
    a.add_argument('--email', default=None)
    a.add_argument('--days', type=int, default=30, help='next_billing_time 까지 일수')
    a.set_defaults(func=cmd_activate)

    u = sub.add_parser('update', help='BILLING.SUBSCRIPTION.UPDATED')
    u.add_argument('--subscription', required=True)
    u.add_argument('--status', default='ACTIVE',
                   choices=['ACTIVE', 'SUSPENDED', 'CANCELLED', 'EXPIRED'])
    u.add_argument('--days', type=int, default=30)
    u.set_defaults(func=cmd_update)

    c = sub.add_parser('cancel', help='BILLING.SUBSCRIPTION.CANCELLED (사용자 직접 해지)')
    c.add_argument('--subscription', required=True)
    c.add_argument('--days', type=int, default=30, help='남은 period 일수')
    c.set_defaults(func=cmd_cancel)

    e = sub.add_parser('expire', help='BILLING.SUBSCRIPTION.EXPIRED (period_end 후 완전 만료)')
    e.add_argument('--subscription', required=True)
    e.set_defaults(func=cmd_expire)

    s = sub.add_parser('suspend', help='BILLING.SUBSCRIPTION.SUSPENDED (결제 실패 past_due)')
    s.add_argument('--subscription', required=True)
    s.set_defaults(func=cmd_suspend)

    pf = sub.add_parser('payment-failed', help='BILLING.SUBSCRIPTION.PAYMENT.FAILED')
    pf.add_argument('--subscription', required=True)
    pf.add_argument('--attempt', type=int, default=1)
    pf.set_defaults(func=cmd_payment_failed)

    ps = sub.add_parser('payment-succeeded', help='PAYMENT.SALE.COMPLETED')
    ps.add_argument('--subscription', required=True)
    ps.add_argument('--amount', type=float, default=4.99)
    ps.add_argument('--currency', default='USD')
    ps.set_defaults(func=cmd_payment_succeeded)

    args = p.parse_args()
    ok = args.func(args, args.url)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
