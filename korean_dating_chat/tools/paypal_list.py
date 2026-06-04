"""PayPal 에 이미 만들어진 Product / Plan 목록 조회.

paypal_setup.py 실행 후 PRODUCT_ID/PLAN_ID 를 못 적어뒀거나 잃어버렸을 때 사용.

사용:
    export PAYPAL_CLIENT_ID=...
    export PAYPAL_CLIENT_SECRET=...
    export PAYPAL_API_BASE=https://api-m.sandbox.paypal.com
    python3 tools/paypal_list.py
"""
import os
import sys
import json
import base64
import urllib.request
import urllib.error

API_BASE = os.getenv('PAYPAL_API_BASE', 'https://api-m.sandbox.paypal.com').rstrip('/')
CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', '')


def _abort(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _get(path, token):
    req = urllib.request.Request(API_BASE + path, method='GET')
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8') if e.fp else ''
        _abort(f"HTTP {e.code}: {raw}")


def get_token():
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode('utf-8')).decode('ascii')
    req = urllib.request.Request(API_BASE + '/v1/oauth2/token', data=b'grant_type=client_credentials', method='POST')
    req.add_header('Authorization', f'Basic {creds}')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))['access_token']
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8') if e.fp else ''
        _abort(f"OAuth 실패 (HTTP {e.code}): {raw}")


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        _abort("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET 환경변수 비어있음.")
    env = 'Sandbox' if 'sandbox' in API_BASE.lower() else 'Live'
    print(f"PayPal API: {API_BASE}  ({env})\n")

    token = get_token()

    print("=" * 60)
    print("Products")
    print("=" * 60)
    products = _get('/v1/catalogs/products?page_size=20', token).get('products', [])
    if not products:
        print("(없음)")
    for p in products:
        print(f"  {p.get('id'):30}  {p.get('name')}")

    print()
    print("=" * 60)
    print("Billing Plans")
    print("=" * 60)
    plans = _get('/v1/billing/plans?page_size=20&total_required=true', token).get('plans', [])
    if not plans:
        print("(없음)")
    for p in plans:
        print(f"  {p.get('id'):30}  {p.get('name'):30}  status={p.get('status')}")
        if p.get('product_id'):
            print(f"    └─ product: {p['product_id']}")

    print()
    print("→ 위 PAYPAL_PLAN_ID (P-...) 를 Secret Manager 에 등록할 값입니다.")


if __name__ == '__main__':
    main()
