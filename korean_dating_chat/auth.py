"""OAuth 로그인 (Google, Kakao) + 세션 cookie.

세션은 itsdangerous 로 서명된 cookie (user_id 만 담음). DB session 테이블 없이 가볍게.
CSRF 방지를 위해 OAuth state 도 cookie 로 왕복.

ENV (production):
  GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
  KAKAO_OAUTH_CLIENT_ID,  KAKAO_OAUTH_CLIENT_SECRET   (Kakao 는 secret optional)
  SESSION_SECRET           (cookie 서명 키 — 절대 노출 X)
  APP_BASE_URL             (https://your-domain — redirect_uri 조립용)

Dev:
  DEV_LOGIN_ENABLED=1 + FLASK_ENV!=production 일 때 /auth/dev-login 활성화
  → 실제 OAuth 키 없어도 로컬 테스트 가능.
"""
import os
import secrets
from urllib.parse import urlencode

import requests
from flask import request, redirect, jsonify, make_response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from users import get_or_create_oauth_user, get_user

# 세션 비밀키. 프로덕션에서는 반드시 강한 값으로 고정 — 변경되면 모든 세션이 무효화됨.
SESSION_SECRET = os.getenv('SESSION_SECRET') or ('dev-only-' + secrets.token_hex(16))
SESSION_COOKIE_NAME = 'kdate_session'
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30일

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_OAUTH_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_OAUTH_CLIENT_SECRET', '')
KAKAO_CLIENT_ID = os.getenv('KAKAO_OAUTH_CLIENT_ID', '')
KAKAO_CLIENT_SECRET = os.getenv('KAKAO_OAUTH_CLIENT_SECRET', '')
BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:8080')

DEV_LOGIN_ENABLED = (
    os.getenv('DEV_LOGIN_ENABLED', '1') == '1'
    and os.getenv('FLASK_ENV') != 'production'
)

_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt='kdate-session-v1')
_STATE_COOKIE = 'kdate_oauth_state'


# ---- 세션 cookie -------------------------------------------------------------

def _sign_user_id(user_id):
    return _serializer.dumps(user_id)


def _verify_token(token):
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def current_user():
    """이 요청의 인증된 사용자 dict. 미인증이면 None."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    user_id = _verify_token(token)
    if not user_id:
        return None
    return get_user(user_id)


def attach_session_cookie(response, user_id):
    response.set_cookie(
        SESSION_COOKIE_NAME,
        _sign_user_id(user_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite='Lax',
        secure=BASE_URL.startswith('https://'),
        path='/',
    )
    return response


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE_NAME, path='/')
    return response


# ---- Google OAuth ------------------------------------------------------------

def google_start():
    if not GOOGLE_CLIENT_ID:
        return jsonify({'error': 'Google 로그인이 설정되지 않았어요.'}), 503
    state = secrets.token_urlsafe(24)
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': f'{BASE_URL}/auth/google/callback',
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'online',
        'prompt': 'select_account',
    }
    resp = make_response(redirect(
        f'https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}'
    ))
    resp.set_cookie(_STATE_COOKIE, state, max_age=600, httponly=True,
                    samesite='Lax', path='/auth/google/')
    return resp


def google_callback():
    if not GOOGLE_CLIENT_ID:
        return 'Google login disabled', 503
    state = request.args.get('state', '')
    expected = request.cookies.get(_STATE_COOKIE, '')
    if not state or state != expected:
        return 'state mismatch', 400
    code = request.args.get('code')
    if not code:
        return 'no code', 400
    try:
        tr = requests.post('https://oauth2.googleapis.com/token', data={
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': f'{BASE_URL}/auth/google/callback',
            'grant_type': 'authorization_code',
        }, timeout=10)
    except requests.RequestException as e:
        print(f'[AUTH] google token network error: {str(e)[:120]}')
        return 'token network error', 502
    if tr.status_code != 200:
        print(f'[AUTH] google token exchange {tr.status_code}: {tr.text[:200]}')
        return 'token exchange failed', 502
    access_token = tr.json().get('access_token')
    if not access_token:
        return 'no access token', 502
    try:
        ur = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
    except requests.RequestException:
        return 'userinfo network error', 502
    if ur.status_code != 200:
        return 'userinfo failed', 502
    info = ur.json()
    user = get_or_create_oauth_user(
        'google',
        info['id'],
        email=info.get('email'),
        display_name=info.get('name'),
    )
    resp = make_response(redirect('/chat'))
    return attach_session_cookie(resp, user['user_id'])


# ---- Kakao OAuth -------------------------------------------------------------

def kakao_start():
    if not KAKAO_CLIENT_ID:
        return jsonify({'error': 'Kakao 로그인이 설정되지 않았어요.'}), 503
    state = secrets.token_urlsafe(24)
    params = {
        'client_id': KAKAO_CLIENT_ID,
        'redirect_uri': f'{BASE_URL}/auth/kakao/callback',
        'response_type': 'code',
        'state': state,
    }
    resp = make_response(redirect(
        f'https://kauth.kakao.com/oauth/authorize?{urlencode(params)}'
    ))
    resp.set_cookie(_STATE_COOKIE, state, max_age=600, httponly=True,
                    samesite='Lax', path='/auth/kakao/')
    return resp


def kakao_callback():
    if not KAKAO_CLIENT_ID:
        return 'Kakao login disabled', 503
    state = request.args.get('state', '')
    expected = request.cookies.get(_STATE_COOKIE, '')
    if not state or state != expected:
        return 'state mismatch', 400
    code = request.args.get('code')
    if not code:
        return 'no code', 400
    payload = {
        'grant_type': 'authorization_code',
        'client_id': KAKAO_CLIENT_ID,
        'redirect_uri': f'{BASE_URL}/auth/kakao/callback',
        'code': code,
    }
    if KAKAO_CLIENT_SECRET:
        payload['client_secret'] = KAKAO_CLIENT_SECRET
    try:
        tr = requests.post('https://kauth.kakao.com/oauth/token', data=payload, timeout=10)
    except requests.RequestException as e:
        print(f'[AUTH] kakao token network error: {str(e)[:120]}')
        return 'token network error', 502
    if tr.status_code != 200:
        print(f'[AUTH] kakao token {tr.status_code}: {tr.text[:200]}')
        return 'token exchange failed', 502
    access_token = tr.json().get('access_token')
    if not access_token:
        return 'no access token', 502
    try:
        ur = requests.get(
            'https://kapi.kakao.com/v2/user/me',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
    except requests.RequestException:
        return 'userinfo network error', 502
    if ur.status_code != 200:
        return 'userinfo failed', 502
    info = ur.json()
    kakao_id = str(info.get('id') or '')
    if not kakao_id:
        return 'no kakao id', 502
    account = info.get('kakao_account') or {}
    profile = account.get('profile') or {}
    user = get_or_create_oauth_user(
        'kakao',
        kakao_id,
        email=account.get('email'),
        display_name=profile.get('nickname'),
    )
    resp = make_response(redirect('/chat'))
    return attach_session_cookie(resp, user['user_id'])


# ---- Dev login (실 OAuth 키 없이 로컬 테스트용) ------------------------------

def dev_login():
    """POST {provider?, provider_user_id?, email?, display_name?} → session 발급.

    FLASK_ENV=production 일 때는 비활성. 실 사용자 노출 금지.
    """
    if not DEV_LOGIN_ENABLED:
        return jsonify({'error': 'disabled'}), 403
    data = request.get_json(silent=True) or {}
    provider = (data.get('provider') or 'dev')[:16]
    pid = str(data.get('provider_user_id') or secrets.token_hex(8))[:64]
    email = (data.get('email') or '')[:200] or None
    display_name = (data.get('display_name') or f'Test User {pid[:6]}')[:60]
    user = get_or_create_oauth_user(provider, pid, email=email, display_name=display_name)
    resp = make_response(jsonify({
        'ok': True,
        'user_id': user['user_id'],
        'display_name': user['display_name'],
        'email': user.get('email'),
    }))
    return attach_session_cookie(resp, user['user_id'])


def logout():
    resp = make_response(jsonify({'ok': True}))
    return clear_session_cookie(resp)
