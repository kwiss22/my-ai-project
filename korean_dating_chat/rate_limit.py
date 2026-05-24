"""인메모리 토큰 버킷 rate limiter.

단일 프로세스 한정 (운영에서 다중 worker 시 Redis 같은 분산 저장소 권장).
플라스크 dev/single-gunicorn-worker 환경에서는 충분.

쓰임:
    from rate_limit import limit
    @app.route(...)
    @limit('chat', per_minute=20, scope='user_or_ip')
    def chat(): ...

scope:
  'ip'           — request.remote_addr 기준
  'user_or_ip'   — current_user() user_id, 없으면 IP
  'global'       — 엔드포인트 전체 (관리 도구 보호용)
"""
import os
import threading
import time
from functools import wraps

from flask import jsonify, request


# (bucket_key) → (tokens, last_refill_ts)
_buckets = {}
_lock = threading.Lock()

# 운영자가 헤더로 임시 우회 (디버그 / 운영 작업용). 보안 핵심이라 SESSION_SECRET 만큼 강해야 함.
_BYPASS_HEADER = 'X-RateLimit-Bypass'
_BYPASS_TOKEN = os.getenv('RATELIMIT_BYPASS_TOKEN', '')


def _refill(tokens, last, capacity, per_seconds):
    """1초당 capacity/per_seconds 만큼 충전. 음수 시간 변동에도 안전."""
    now = time.time()
    elapsed = max(0.0, now - last)
    refilled = min(capacity, tokens + elapsed * (capacity / per_seconds))
    return refilled, now


def _bucket_key(name, scope):
    """엔드포인트 + scope 식별자 조합."""
    if scope == 'global':
        return f'{name}:global'
    if scope == 'ip':
        return f'{name}:ip:{request.remote_addr}'
    if scope == 'user_or_ip':
        # current_user() 는 auth.py 에 있고 — 순환 import 회피 위해 지연 로드
        try:
            from auth import current_user
            u = current_user()
            if u and u.get('user_id'):
                return f'{name}:u:{u["user_id"]}'
        except Exception:
            pass
        return f'{name}:ip:{request.remote_addr}'
    return f'{name}:ip:{request.remote_addr}'


def _try_consume(key, capacity, per_seconds, cost=1):
    """토큰 cost 만큼 차감 시도. (allowed, retry_after_seconds)."""
    with _lock:
        tokens, last = _buckets.get(key, (capacity, time.time()))
        tokens, last = _refill(tokens, last, capacity, per_seconds)
        if tokens >= cost:
            _buckets[key] = (tokens - cost, last)
            return (True, 0)
        # 남은 토큰이 cost 가 될 때까지 필요한 시간
        deficit = cost - tokens
        retry_after = deficit * (per_seconds / capacity)
        _buckets[key] = (tokens, last)
        return (False, retry_after)


def limit(name, per_minute=None, per_hour=None, scope='user_or_ip', cost=1):
    """Rate limit decorator. per_minute 또는 per_hour 중 하나 지정."""
    if per_minute is not None:
        capacity, per_seconds = per_minute, 60.0
    elif per_hour is not None:
        capacity, per_seconds = per_hour, 3600.0
    else:
        raise ValueError('per_minute 또는 per_hour 필요')

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # 운영자 우회 헤더 (테스트/긴급 작업)
            if _BYPASS_TOKEN and request.headers.get(_BYPASS_HEADER) == _BYPASS_TOKEN:
                return fn(*args, **kwargs)
            key = _bucket_key(name, scope)
            allowed, retry_after = _try_consume(key, capacity, per_seconds, cost)
            if allowed:
                return fn(*args, **kwargs)
            # 429 Too Many Requests
            retry_seconds = max(1, int(retry_after + 0.5))
            resp = jsonify({
                'error': '요청이 너무 잦아요. 잠시 후 다시 시도해주세요.',
                'retry_after': retry_seconds,
            })
            resp.status_code = 429
            resp.headers['Retry-After'] = str(retry_seconds)
            return resp
        return wrapper
    return deco


def stats():
    """모니터링·테스트용. 현재 활성 버킷 수 + 가장 가까운 reset 까지 남은 시간."""
    with _lock:
        return {
            'active_buckets': len(_buckets),
            'sample_keys': list(_buckets.keys())[:10],
        }


def reset_all():
    """테스트 전용. 운영 코드에서 호출 X."""
    with _lock:
        _buckets.clear()
