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
from users import _connect

ADMIN_EMAILS = set(
    e.strip().lower() for e in (os.getenv('ADMIN_EMAILS', '') or '').split(',') if e.strip()
)
PRICE_USD_MONTHLY = float(os.getenv('PRICE_USD_MONTHLY', '4.99'))


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
    today_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    seven_days_ago = now_ts - 7 * 86400
    thirty_days_ago = now_ts - 30 * 86400

    conn = _connect()
    try:
        # 가입자 집계
        total_users = conn.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']
        by_provider = {
            row['provider']: row['n']
            for row in conn.execute(
                'SELECT provider, COUNT(*) AS n FROM users GROUP BY provider'
            ).fetchall()
        }
        new_today = conn.execute(
            'SELECT COUNT(*) AS n FROM users WHERE created_at >= ?',
            (now_ts - 86400,),
        ).fetchone()['n']
        new_7 = conn.execute(
            'SELECT COUNT(*) AS n FROM users WHERE created_at >= ?',
            (seven_days_ago,),
        ).fetchone()['n']
        new_30 = conn.execute(
            'SELECT COUNT(*) AS n FROM users WHERE created_at >= ?',
            (thirty_days_ago,),
        ).fetchone()['n']

        # 구독자 상태 집계 (has_active_subscription 정의와 일치)
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM users "
            "WHERE subscription_status IN ('active','trialing','past_due','canceled') "
            "AND subscription_period_end > ?",
            (now_ts,),
        ).fetchone()['n']
        trialing = conn.execute(
            "SELECT COUNT(*) AS n FROM users "
            "WHERE subscription_status='trialing' AND subscription_period_end > ?",
            (now_ts,),
        ).fetchone()['n']
        past_due = conn.execute(
            "SELECT COUNT(*) AS n FROM users "
            "WHERE subscription_status='past_due' AND subscription_period_end > ?",
            (now_ts,),
        ).fetchone()['n']
        scheduled_cancel = conn.execute(
            "SELECT COUNT(*) AS n FROM users "
            "WHERE subscription_cancel_at_period_end=1 AND subscription_period_end > ?",
            (now_ts,),
        ).fetchone()['n']
        canceled = conn.execute(
            "SELECT COUNT(*) AS n FROM users "
            "WHERE subscription_status='canceled' "
            "AND (subscription_period_end IS NULL OR subscription_period_end <= ?)",
            (now_ts,),
        ).fetchone()['n']

        # 오늘 cap 도달자 (페이월 전환 funnel)
        from users import DAILY_FREE_QUOTA
        today_capped = conn.execute(
            "SELECT COUNT(*) AS n FROM users "
            "WHERE daily_reset_date=? AND daily_chat_count >= ? "
            "AND (subscription_status IS NULL "
            "     OR subscription_period_end IS NULL "
            "     OR subscription_period_end <= ?)",
            (today_utc, DAILY_FREE_QUOTA, now_ts),
        ).fetchone()['n']
    finally:
        conn.close()

    return jsonify({
        'users': {
            'total': total_users,
            'by_provider': by_provider,
            'new_today': new_today,
            'new_7days': new_7,
            'new_30days': new_30,
        },
        'subscribers': {
            'active': active,
            'trialing': trialing,
            'past_due': past_due,
            'cancel_at_period_end': scheduled_cancel,
            'canceled': canceled,
        },
        'revenue': {
            'estimated_mrr_usd': round(active * PRICE_USD_MONTHLY, 2),
            'price_assumed_usd': PRICE_USD_MONTHLY,
        },
        'quota': {
            'today_capped': today_capped,
        },
        'as_of': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    })
