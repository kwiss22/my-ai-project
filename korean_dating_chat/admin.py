"""운영자 관측성 — /admin/stats (가입·유료·MRR 집계).

보호: ADMIN_EMAILS 환경변수에 쉼표로 구분된 이메일 화이트리스트.
현재 로그인 사용자의 email 이 그 목록에 있어야 통과.

ENV:
  ADMIN_EMAILS=ops@example.com,founder@example.com
  PRICE_USD_MONTHLY=4.99    # MRR 계산용. Stripe 가격과 일치시키기.
"""
import os
import time
from datetime import datetime, timezone, timedelta

from flask import jsonify, request

from auth import current_user
from users import (
    DAILY_FREE_QUOTA, _today,
    stats_snapshot as _users_stats_snapshot,
    reset_all as _users_reset_all,
)
from events import read_recent as events_read_recent, summary_last_7d as events_summary_7d
import alerts as _alerts

ADMIN_EMAILS = set(
    e.strip().lower() for e in (os.getenv('ADMIN_EMAILS', '') or '').split(',') if e.strip()
)
PRICE_USD_MONTHLY = float(os.getenv('PRICE_USD_MONTHLY', '4.99'))


def is_admin(user):
    """공개 헬퍼 — HTML 페이지 가드 등 외부에서 호출."""
    return _is_admin(user)


def admin_enabled():
    """ADMIN_EMAILS 화이트리스트가 설정돼 있는지."""
    return bool(ADMIN_EMAILS)


def _is_admin(user):
    if not user or not user.get('email'):
        return False
    return user['email'].lower() in ADMIN_EMAILS


def _require_admin():
    """관리자 인증 헬퍼. (allowed, error_response)"""
    if not ADMIN_EMAILS:
        # 환경변수 미설정 → 모든 요청 차단 (운영자가 명시적으로 설정해야 enable)
        return (False, (jsonify({'error': 'admin disabled (ADMIN_EMAILS unset)'}), 503))
    user = current_user()
    if not user:
        return (False, (jsonify({'error': '로그인이 필요해요.'}), 401))
    if not _is_admin(user):
        return (False, (jsonify({'error': 'forbidden'}), 403))
    return (True, None)


def stats():
    """대시보드용 종합 통계. JSON 응답.

    {
      "users": {
        "total":             전체 가입자 수
        "by_provider":       {google: N, dev: M, ...}
        "new_today":         오늘(UTC) 신규 가입
        "new_7days":         최근 7일 신규
        "new_30days":        최근 30일 신규
      },
      "subscribers": {
        "active":            현재 활성 구독자 (period_end 미래 + status active/trialing/past_due/canceled)
        "trialing":
        "past_due":
        "cancel_at_period_end":  해지 예약된 사용자 (period_end 까지는 active)
        "canceled":              완전 해지 (period_end 과거)
      },
      "revenue": {
        "estimated_mrr_usd":   active 구독자 × PRICE_USD_MONTHLY
        "price_assumed_usd":   PRICE_USD_MONTHLY
      },
      "quota": {
        "today_capped":        오늘 cap 도달한 비구독 사용자 수 (페이월 전환 funnel)
      },
      "as_of": "2026-05-24T12:34:56Z"
    }
    """
    ok, err = _require_admin()
    if not ok:
        return err

    now_ts = int(time.time())
    today = _today()

    # 백엔드 무관 — UserStore 가 집계해서 dict 로 반환
    snap = _users_stats_snapshot(today, now_ts, DAILY_FREE_QUOTA)

    new_since = snap['new_since']
    active = snap['subscribers']['active']

    return jsonify({
        'users': {
            'total': snap['total'],
            'by_provider': snap['by_provider'],
            'new_today':  new_since[now_ts - 86400],
            'new_7days':  new_since[now_ts - 7 * 86400],
            'new_30days': new_since[now_ts - 30 * 86400],
        },
        'subscribers': snap['subscribers'],
        'revenue': {
            'estimated_mrr_usd': round(active * PRICE_USD_MONTHLY, 2),
            'price_assumed_usd': PRICE_USD_MONTHLY,
        },
        'quota': {
            'today_capped': snap['today_capped'],
        },
        'events_7d': events_summary_7d(),
        'as_of': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    })


def events():
    """최근 이벤트 로그 조회. ?limit=N&severity=critical&kind=payment.failed&kind_prefix=subscription."""
    ok, err = _require_admin()
    if not ok:
        return err
    try:
        limit = min(500, max(1, int(request.args.get('limit', '100'))))
    except ValueError:
        limit = 100
    severity = request.args.get('severity') or None
    kind = request.args.get('kind') or None
    kind_prefix = request.args.get('kind_prefix') or None
    recs = events_read_recent(limit=limit, severity=severity, kind=kind, kind_prefix=kind_prefix)
    return jsonify({'events': recs, 'count': len(recs)})


def alerts_health():
    """알림 채널 설정 진단. 키 값은 노출 X — 활성/비활성 상태만."""
    ok, err = _require_admin()
    if not ok:
        return err
    return jsonify({
        'min_severity': _alerts.MIN_SEVERITY,
        'dedup_seconds': _alerts.DEDUP_SECONDS,
        'channels': {
            'slack': _alerts.slack_enabled(),
            'smtp':  _alerts.smtp_enabled(),
            'test_sink': _alerts.TEST_SINK,
        },
        'any_enabled': _alerts.any_enabled(),
    })


def alerts_test_sink():
    """ALERT_TEST_SINK=1 일 때 메모리에 적재된 알림 조회. 통합 테스트용."""
    ok, err = _require_admin()
    if not ok:
        return err
    if not _alerts.TEST_SINK:
        return jsonify({'error': 'test sink disabled', 'enable_with': 'ALERT_TEST_SINK=1'}), 503
    return jsonify({'sink': _alerts.get_test_sink()})


def test_reset():
    """통합 테스트용 상태 초기화 — DB users 비우기, events.jsonl 삭제,
    rate-limit 버킷 / alert dedup / test sink 초기화.

    안전 게이트: ENV_ALLOW_TEST_RESET=1 이고 FLASK_ENV != 'production' 일 때만 동작.
    프로덕션에서는 명시적으로 503 반환.
    """
    if os.getenv('FLASK_ENV') == 'production':
        return jsonify({'error': 'disabled in production'}), 503
    if os.getenv('ENV_ALLOW_TEST_RESET') != '1':
        return jsonify({'error': 'set ENV_ALLOW_TEST_RESET=1 to enable'}), 503

    # 인증·관리자 화이트리스트 거치지 않음 — 테스트 도구. 다만 위 두 가드로 운영 차단.
    # 사용자 저장소 비우기 (백엔드 무관)
    _users_reset_all()

    # events.jsonl 삭제
    from events import EVENTS_LOG_PATH
    try:
        if os.path.exists(EVENTS_LOG_PATH):
            os.remove(EVENTS_LOG_PATH)
    except OSError:
        pass

    # rate-limit + alert dedup + test sink 초기화
    try:
        from rate_limit import reset_all as _rl_reset
        _rl_reset()
    except Exception:
        pass
    try:
        _alerts.reset_dedup()
        _alerts.clear_test_sink()
    except Exception:
        pass

    return jsonify({'ok': True, 'reset': ['users', 'events', 'rate_limit', 'alert_dedup', 'test_sink']})
