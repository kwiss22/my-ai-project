"""사용자 저장소 + 일일 quota + 구독 상태.

SQLite 단일 파일 백엔드 (로컬·서버 동일). USERS_DB_PATH 환경변수로 위치 변경.
- 신규 가입은 OAuth(Google) 콜백에서 get_or_create_oauth_user 로만 진행
- 일일 quota 는 QUOTA_TIMEZONE 자정 기준 자동 리셋 (기본 UTC, 'Asia/Seoul' 권장)
- 구독 상태는 Stripe webhook 이 set_subscription / clear_subscription 호출
- past_due (결제 재시도 중) 와 cancel_at_period_end 둘 다 grace 처리:
  사용자가 카드 만료/취소 직후 바로 차단당하지 않음.
"""
import os
import sqlite3
import secrets
import time
from datetime import datetime, timezone

DB_PATH = os.getenv('USERS_DB_PATH', os.path.join(os.path.dirname(__file__), 'kdate_users.db'))

# 무료 일일 메시지 한도. 환경변수로 운영 중에도 조정 가능.
DAILY_FREE_QUOTA = int(os.getenv('DAILY_FREE_QUOTA', '25'))

# Quota 자정 리셋 기준 timezone. 한국 사용자 위주면 'Asia/Seoul' 권장.
# zoneinfo 가 인식 못 하면 UTC 로 폴백.
QUOTA_TIMEZONE = os.getenv('QUOTA_TIMEZONE', 'UTC')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,                  -- 'google' | 'dev'
  provider_user_id TEXT NOT NULL,
  email TEXT,
  display_name TEXT,
  created_at INTEGER NOT NULL,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  subscription_status TEXT,                -- 'active' | 'trialing' | 'past_due' | 'canceled' | NULL
  subscription_period_end INTEGER,         -- unix seconds (현재 결제 주기 종료)
  subscription_cancel_at_period_end INTEGER NOT NULL DEFAULT 0,  -- 1=해지 예약됨
  daily_chat_count INTEGER NOT NULL DEFAULT 0,
  daily_reset_date TEXT NOT NULL,          -- 'YYYY-MM-DD' (QUOTA_TIMEZONE 기준)
  UNIQUE(provider, provider_user_id)
);
CREATE INDEX IF NOT EXISTS users_stripe_customer ON users(stripe_customer_id);
"""

# 기존 DB 가 있을 때 신규 컬럼을 ALTER 로 추가 (PRAGMA 로 존재 여부 확인 후).
_MIGRATIONS = [
    ('subscription_cancel_at_period_end',
     'ALTER TABLE users ADD COLUMN subscription_cancel_at_period_end INTEGER NOT NULL DEFAULT 0'),
]


def _today():
    """오늘 날짜 ('YYYY-MM-DD'). QUOTA_TIMEZONE 기준. zoneinfo 실패 시 UTC."""
    if QUOTA_TIMEZONE and QUOTA_TIMEZONE != 'UTC':
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(QUOTA_TIMEZONE)).strftime('%Y-%m-%d')
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """앱 시작 시 한 번 호출. 테이블이 없으면 생성, 신규 컬럼은 ALTER 로 추가."""
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        # 기존 DB 호환: 컬럼 존재 여부 확인 후 누락 시 ALTER.
        existing = {row['name'] for row in conn.execute('PRAGMA table_info(users)').fetchall()}
        for col, ddl in _MIGRATIONS:
            if col not in existing:
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # idempotent
        conn.commit()
    finally:
        conn.close()


def get_or_create_oauth_user(provider, provider_user_id, email=None, display_name=None):
    """OAuth 콜백에서 호출. 기존 사용자면 email/name 갱신, 없으면 신규."""
    today = _today()
    now = int(time.time())
    conn = _connect()
    try:
        row = conn.execute(
            'SELECT * FROM users WHERE provider=? AND provider_user_id=?',
            (provider, provider_user_id),
        ).fetchone()
        if row:
            # 프로필 정보가 들어오면 보충 (COALESCE 로 빈 값 보호)
            conn.execute(
                'UPDATE users SET email=COALESCE(?, email), display_name=COALESCE(?, display_name) WHERE user_id=?',
                (email, display_name, row['user_id']),
            )
            conn.commit()
            return dict(conn.execute('SELECT * FROM users WHERE user_id=?', (row['user_id'],)).fetchone())
        user_id = secrets.token_urlsafe(16)
        conn.execute(
            'INSERT INTO users (user_id, provider, provider_user_id, email, display_name, created_at, daily_chat_count, daily_reset_date) '
            'VALUES (?, ?, ?, ?, ?, ?, 0, ?)',
            (user_id, provider, provider_user_id, email, display_name, now, today),
        )
        conn.commit()
        return dict(conn.execute('SELECT * FROM users WHERE user_id=?', (user_id,)).fetchone())
    finally:
        conn.close()


def get_user(user_id):
    if not user_id:
        return None
    conn = _connect()
    try:
        row = conn.execute('SELECT * FROM users WHERE user_id=?', (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_stripe_customer(customer_id):
    if not customer_id:
        return None
    conn = _connect()
    try:
        row = conn.execute('SELECT * FROM users WHERE stripe_customer_id=?', (customer_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def has_active_subscription(user):
    """user dict 가 현재 시점에 유효 구독자인지.

    grace policy:
      - 'active', 'trialing' : 정상 활성
      - 'past_due'           : Stripe 가 결제 재시도 중 (보통 ~1주). period_end 까지는 활성 유지.
      - 'canceled'           : 즉시 만료. 단, period_end 가 미래면 cancel_at_period_end 해지 예약
                               이라 기간 끝까지는 활성. period_end 가 지났으면 비활성.
    """
    if not user:
        return False
    status = user.get('subscription_status')
    if status not in ('active', 'trialing', 'past_due', 'canceled'):
        return False
    end = user.get('subscription_period_end') or 0
    return end > int(time.time())


def consume_quota(user_id, cap=None):
    """일일 quota 차감 시도. (allowed, remaining_after, reset_date) 반환.

    - 새 날(UTC)이면 카운터 리셋 후 차감
    - 이미 cap 도달 → allowed=False, count 증가 X
    - 차감되면 count++ (트랜잭션)
    """
    if cap is None:
        cap = DAILY_FREE_QUOTA
    today = _today()
    conn = _connect()
    try:
        with conn:
            row = conn.execute(
                'SELECT daily_chat_count, daily_reset_date FROM users WHERE user_id=?',
                (user_id,),
            ).fetchone()
            if not row:
                return (False, 0, today)
            count = row['daily_chat_count']
            if row['daily_reset_date'] != today:
                count = 0
                conn.execute(
                    'UPDATE users SET daily_chat_count=0, daily_reset_date=? WHERE user_id=?',
                    (today, user_id),
                )
            if count >= cap:
                return (False, 0, today)
            conn.execute(
                'UPDATE users SET daily_chat_count=daily_chat_count+1 WHERE user_id=?',
                (user_id,),
            )
            return (True, cap - count - 1, today)
    finally:
        conn.close()


def peek_quota(user_id, cap=None):
    """차감 없이 현재 상태만 조회. (used, cap, remaining, reset_date)."""
    if cap is None:
        cap = DAILY_FREE_QUOTA
    today = _today()
    conn = _connect()
    try:
        row = conn.execute(
            'SELECT daily_chat_count, daily_reset_date FROM users WHERE user_id=?',
            (user_id,),
        ).fetchone()
        if not row:
            return (0, cap, cap, today)
        count = row['daily_chat_count'] if row['daily_reset_date'] == today else 0
        return (count, cap, max(0, cap - count), today)
    finally:
        conn.close()


def set_subscription(user_id, stripe_customer_id, stripe_subscription_id, status, period_end,
                     cancel_at_period_end=None):
    """구독 상태 저장. cancel_at_period_end=None 이면 기존 값 유지."""
    conn = _connect()
    try:
        if cancel_at_period_end is None:
            conn.execute(
                'UPDATE users SET stripe_customer_id=?, stripe_subscription_id=?, '
                'subscription_status=?, subscription_period_end=? WHERE user_id=?',
                (stripe_customer_id, stripe_subscription_id, status, period_end, user_id),
            )
        else:
            conn.execute(
                'UPDATE users SET stripe_customer_id=?, stripe_subscription_id=?, '
                'subscription_status=?, subscription_period_end=?, '
                'subscription_cancel_at_period_end=? WHERE user_id=?',
                (stripe_customer_id, stripe_subscription_id, status, period_end,
                 1 if cancel_at_period_end else 0, user_id),
            )
        conn.commit()
    finally:
        conn.close()


def delete_user(user_id):
    """사용자 행 완전 삭제. 호출 전에 Stripe 구독은 별도 취소해야 함."""
    if not user_id:
        return False
    conn = _connect()
    try:
        cur = conn.execute('DELETE FROM users WHERE user_id=?', (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_subscription(user_id):
    conn = _connect()
    try:
        conn.execute(
            'UPDATE users SET subscription_status=?, subscription_period_end=NULL, '
            'subscription_cancel_at_period_end=0 WHERE user_id=?',
            ('canceled', user_id),
        )
        conn.commit()
    finally:
        conn.close()
