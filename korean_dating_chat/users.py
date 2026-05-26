"""사용자 저장소 + 일일 quota + 구독 상태.

백엔드 추상화. 기본 구현은 SQLite, 환경변수 USERS_BACKEND 로 향후 Firestore 등으로
교체 가능. 호출 측 (chatbot/auth/billing/admin) 은 모듈 레벨 함수만 사용 — 백엔드
교체 시 호출 측 변경 없음.

- 신규 가입은 OAuth(Google) 콜백에서 get_or_create_oauth_user 로만 진행
- 일일 quota 는 QUOTA_TIMEZONE 자정 기준 자동 리셋 (기본 UTC, 'Asia/Seoul' 권장)
- 구독 상태는 Stripe webhook 이 set_subscription / clear_subscription 호출
- past_due (결제 재시도 중) 와 cancel_at_period_end 둘 다 grace 처리

향후 Firestore 백엔드 추가하려면:
  1. UserStore 를 상속한 FirestoreUserStore 클래스 작성 (이 파일에 추가하거나 별도 모듈)
  2. _select_backend() 의 분기에 'firestore' 추가
  3. USERS_BACKEND=firestore 환경변수 설정
  호출 측 (chatbot/auth/billing/admin) 코드 변경 없음.
"""
import abc
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone

DB_PATH = os.getenv('USERS_DB_PATH', os.path.join(os.path.dirname(__file__), 'kdate_users.db'))

# 무료 일일 메시지 한도. 환경변수로 운영 중에도 조정 가능.
DAILY_FREE_QUOTA = int(os.getenv('DAILY_FREE_QUOTA', '25'))

# Quota 자정 리셋 기준 timezone. 한국 사용자 위주면 'Asia/Seoul' 권장.
# zoneinfo 가 인식 못 하면 UTC 로 폴백.
QUOTA_TIMEZONE = os.getenv('QUOTA_TIMEZONE', 'UTC')

# 백엔드 선택. 'sqlite' (기본) | 'firestore' (향후) | 'memory' (테스트용).
USERS_BACKEND = os.getenv('USERS_BACKEND', 'sqlite').lower()


def _today():
    """오늘 날짜 ('YYYY-MM-DD'). QUOTA_TIMEZONE 기준. zoneinfo 실패 시 UTC."""
    if QUOTA_TIMEZONE and QUOTA_TIMEZONE != 'UTC':
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(QUOTA_TIMEZONE)).strftime('%Y-%m-%d')
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def has_active_subscription(user):
    """user dict 가 현재 시점에 유효 구독자인지. 순수 함수 — 백엔드 무관.

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


# =============================================================================
# UserStore — 백엔드 추상 인터페이스
# =============================================================================

class UserStore(abc.ABC):
    """저장소 인터페이스. 모든 구현은 dict 형태로 사용자 row 를 반환·소비."""

    @abc.abstractmethod
    def init(self):
        """앱 시작 시 한 번 호출. 스키마/마이그레이션 등 backend-specific 초기화."""

    @abc.abstractmethod
    def get_or_create_oauth_user(self, provider, provider_user_id,
                                 email=None, display_name=None):
        """OAuth 콜백. 기존 사용자면 email/name 보충 update, 없으면 신규 생성. user dict 반환."""

    @abc.abstractmethod
    def get_user(self, user_id):
        """user_id 로 조회. 없으면 None."""

    @abc.abstractmethod
    def get_user_by_stripe_customer(self, customer_id):
        """Stripe customer_id 로 조회. webhook 처리용."""

    @abc.abstractmethod
    def consume_quota(self, user_id, cap):
        """일일 quota 차감 시도. (allowed, remaining_after, reset_date) 반환.
        새 날이면 카운터 리셋 후 차감. cap 도달이면 (False, 0, today).
        구현은 반드시 atomic — 동시 호출에서 cap 초과 방지."""

    @abc.abstractmethod
    def peek_quota(self, user_id, cap):
        """차감 없이 조회. (used, cap, remaining, reset_date)."""

    @abc.abstractmethod
    def set_subscription(self, user_id, stripe_customer_id, stripe_subscription_id,
                         status, period_end, cancel_at_period_end=None):
        """구독 상태 저장. cancel_at_period_end=None 이면 기존 값 유지."""

    @abc.abstractmethod
    def clear_subscription(self, user_id):
        """구독 완전 해지. status='canceled', period_end=None, cancel_at_period_end=0."""

    @abc.abstractmethod
    def delete_user(self, user_id):
        """사용자 행 완전 삭제. 호출 전에 Stripe 구독은 별도 취소돼야 함. 성공 시 True."""

    @abc.abstractmethod
    def stats_snapshot(self, today, now_ts, free_quota_cap):
        """admin 대시보드용 집계 스냅샷.

        반환 dict 형식:
          {'total': N,
           'by_provider': {'google': N, 'dev': N, ...},
           'new_since': {(now_ts - 86400): N, (now_ts - 7*86400): N, (now_ts - 30*86400): N},
                                                    # 키 = 컷오프 unix ts
           'subscribers': {'active': N, 'trialing': N, 'past_due': N,
                           'cancel_at_period_end': N, 'canceled': N},
           'today_capped': N,
          }
        """

    @abc.abstractmethod
    def reset_all(self):
        """테스트 전용. 모든 사용자 삭제. /admin/test-reset 에서 호출."""


# =============================================================================
# SQLite 구현 — 단일 파일 백엔드 (로컬·소규모 운영)
# =============================================================================

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

_MIGRATIONS = [
    ('subscription_cancel_at_period_end',
     'ALTER TABLE users ADD COLUMN subscription_cancel_at_period_end INTEGER NOT NULL DEFAULT 0'),
]


class SQLiteUserStore(UserStore):
    def __init__(self, db_path):
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
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

    def get_or_create_oauth_user(self, provider, provider_user_id, email=None, display_name=None):
        today = _today()
        now = int(time.time())
        conn = self._connect()
        try:
            row = conn.execute(
                'SELECT * FROM users WHERE provider=? AND provider_user_id=?',
                (provider, provider_user_id),
            ).fetchone()
            if row:
                conn.execute(
                    'UPDATE users SET email=COALESCE(?, email), display_name=COALESCE(?, display_name) WHERE user_id=?',
                    (email, display_name, row['user_id']),
                )
                conn.commit()
                return dict(conn.execute('SELECT * FROM users WHERE user_id=?', (row['user_id'],)).fetchone())
            user_id = secrets.token_urlsafe(16)
            conn.execute(
                'INSERT INTO users (user_id, provider, provider_user_id, email, display_name, '
                'created_at, daily_chat_count, daily_reset_date) VALUES (?, ?, ?, ?, ?, ?, 0, ?)',
                (user_id, provider, provider_user_id, email, display_name, now, today),
            )
            conn.commit()
            return dict(conn.execute('SELECT * FROM users WHERE user_id=?', (user_id,)).fetchone())
        finally:
            conn.close()

    def get_user(self, user_id):
        if not user_id:
            return None
        conn = self._connect()
        try:
            row = conn.execute('SELECT * FROM users WHERE user_id=?', (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_user_by_stripe_customer(self, customer_id):
        if not customer_id:
            return None
        conn = self._connect()
        try:
            row = conn.execute('SELECT * FROM users WHERE stripe_customer_id=?', (customer_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def consume_quota(self, user_id, cap):
        today = _today()
        conn = self._connect()
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

    def peek_quota(self, user_id, cap):
        today = _today()
        conn = self._connect()
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

    def set_subscription(self, user_id, stripe_customer_id, stripe_subscription_id,
                         status, period_end, cancel_at_period_end=None):
        conn = self._connect()
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

    def clear_subscription(self, user_id):
        conn = self._connect()
        try:
            conn.execute(
                'UPDATE users SET subscription_status=?, subscription_period_end=NULL, '
                'subscription_cancel_at_period_end=0 WHERE user_id=?',
                ('canceled', user_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_user(self, user_id):
        if not user_id:
            return False
        conn = self._connect()
        try:
            cur = conn.execute('DELETE FROM users WHERE user_id=?', (user_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def stats_snapshot(self, today, now_ts, free_quota_cap):
        conn = self._connect()
        try:
            total = conn.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']
            by_provider = {
                row['provider']: row['n']
                for row in conn.execute(
                    'SELECT provider, COUNT(*) AS n FROM users GROUP BY provider'
                ).fetchall()
            }
            new_since = {}
            for cutoff in (now_ts - 86400, now_ts - 7 * 86400, now_ts - 30 * 86400):
                new_since[cutoff] = conn.execute(
                    'SELECT COUNT(*) AS n FROM users WHERE created_at >= ?', (cutoff,),
                ).fetchone()['n']

            active = conn.execute(
                "SELECT COUNT(*) AS n FROM users "
                "WHERE subscription_status IN ('active','trialing','past_due','canceled') "
                "AND subscription_period_end > ?", (now_ts,),
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

            today_capped = conn.execute(
                "SELECT COUNT(*) AS n FROM users "
                "WHERE daily_reset_date=? AND daily_chat_count >= ? "
                "AND (subscription_status IS NULL "
                "     OR subscription_period_end IS NULL "
                "     OR subscription_period_end <= ?)",
                (today, free_quota_cap, now_ts),
            ).fetchone()['n']

            return {
                'total': total,
                'by_provider': by_provider,
                'new_since': new_since,
                'subscribers': {
                    'active': active,
                    'trialing': trialing,
                    'past_due': past_due,
                    'cancel_at_period_end': scheduled_cancel,
                    'canceled': canceled,
                },
                'today_capped': today_capped,
            }
        finally:
            conn.close()

    def reset_all(self):
        conn = self._connect()
        try:
            conn.execute('DELETE FROM users')
            conn.commit()
        finally:
            conn.close()


# =============================================================================
# 백엔드 인스턴스 선택 + 모듈 레벨 thin wrapper
# =============================================================================

def _select_backend():
    if USERS_BACKEND == 'sqlite':
        return SQLiteUserStore(DB_PATH)
    # 향후 추가:
    # if USERS_BACKEND == 'firestore':
    #     from users_firestore import FirestoreUserStore
    #     return FirestoreUserStore()
    raise ValueError(f"Unknown USERS_BACKEND: {USERS_BACKEND!r}")


_store: UserStore = _select_backend()


def init_db():
    """앱 시작 시 한 번 호출."""
    _store.init()


def get_or_create_oauth_user(provider, provider_user_id, email=None, display_name=None):
    return _store.get_or_create_oauth_user(provider, provider_user_id, email, display_name)


def get_user(user_id):
    return _store.get_user(user_id)


def get_user_by_stripe_customer(customer_id):
    return _store.get_user_by_stripe_customer(customer_id)


def consume_quota(user_id, cap=None):
    if cap is None:
        cap = DAILY_FREE_QUOTA
    return _store.consume_quota(user_id, cap)


def peek_quota(user_id, cap=None):
    if cap is None:
        cap = DAILY_FREE_QUOTA
    return _store.peek_quota(user_id, cap)


def set_subscription(user_id, stripe_customer_id, stripe_subscription_id, status, period_end,
                     cancel_at_period_end=None):
    return _store.set_subscription(user_id, stripe_customer_id, stripe_subscription_id,
                                   status, period_end, cancel_at_period_end)


def clear_subscription(user_id):
    return _store.clear_subscription(user_id)


def delete_user(user_id):
    return _store.delete_user(user_id)


def stats_snapshot(today, now_ts, free_quota_cap=None):
    """admin 대시보드용. free_quota_cap 생략 시 DAILY_FREE_QUOTA 사용."""
    if free_quota_cap is None:
        free_quota_cap = DAILY_FREE_QUOTA
    return _store.stats_snapshot(today, now_ts, free_quota_cap)


def reset_all():
    """테스트 전용. /admin/test-reset 에서 호출."""
    return _store.reset_all()


# 백워드 호환 — 외부에서 _connect() 를 import 하던 코드는 deprecated.
# 직접 SQL 이 꼭 필요하면 store._connect() 또는 새 메서드 추가 권장.
def _connect():
    """deprecated — backend-agnostic 코드로 마이그레이션 필요."""
    if isinstance(_store, SQLiteUserStore):
        return _store._connect()
    raise RuntimeError(f"_connect() is SQLite-only; current backend: {USERS_BACKEND}")
