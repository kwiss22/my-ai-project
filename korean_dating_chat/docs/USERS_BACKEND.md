# 사용자 저장소 백엔드

`users.py` 는 `UserStore` 추상 클래스를 정의하고 `SQLiteUserStore` 가 기본 구현.
호출 측 (chatbot/auth/billing/admin) 은 모듈 레벨 함수만 사용 — 백엔드 교체 시
호출 측 코드 변경 X.

## 현재 백엔드

- 기본: **SQLite** (`USERS_BACKEND=sqlite`)
- 단일 파일 `kdate_users.db`. Cloud Run 에서는 GCS Fuse 볼륨에 마운트.
- max-instances=1 (단일 작성자 제약)

## 백엔드 추가 — Firestore 예시

수백 동시 사용자 / 다중 인스턴스가 필요해지면 Firestore 로 마이그레이션.
작업 순서:

### 1. 새 클래스 작성 (예: `users_firestore.py`)

```python
from google.cloud import firestore
from users import UserStore

class FirestoreUserStore(UserStore):
    def __init__(self, project=None):
        self._db = firestore.Client(project=project)
        self._users = self._db.collection('users')

    def init(self):
        # Firestore 는 스키마리스. 인덱스만 필요시 콘솔에서 생성.
        pass

    def get_or_create_oauth_user(self, provider, provider_user_id, email=None, display_name=None):
        # provider + provider_user_id 로 쿼리 → 없으면 생성
        ...

    def get_user(self, user_id):
        doc = self._users.document(user_id).get()
        return doc.to_dict() if doc.exists else None

    def consume_quota(self, user_id, cap):
        # Firestore Transaction 으로 atomic increment
        @firestore.transactional
        def _tx(tx, ref):
            snap = ref.get(transaction=tx).to_dict()
            ...
        return _tx(self._db.transaction(), self._users.document(user_id))

    # ... 나머지 메서드도 동일하게 구현
```

### 2. `users.py` 의 `_select_backend()` 분기에 추가

```python
def _select_backend():
    if USERS_BACKEND == 'sqlite':
        return SQLiteUserStore(DB_PATH)
    if USERS_BACKEND == 'firestore':
        from users_firestore import FirestoreUserStore
        return FirestoreUserStore()
    raise ValueError(f"Unknown USERS_BACKEND: {USERS_BACKEND!r}")
```

### 3. 환경변수 설정 + 데이터 마이그레이션

```bash
# 1. SQLite → JSON dump
python3 -c "
import sqlite3, json
conn = sqlite3.connect('kdate_users.db')
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute('SELECT * FROM users')]
print(json.dumps(rows, ensure_ascii=False, indent=2))
" > users_dump.json

# 2. Firestore 로 임포트 (스크립트 별도)
python3 import_to_firestore.py users_dump.json

# 3. Cloud Run 재배포 시 USERS_BACKEND=firestore 추가
```

### 4. Cloud Run 인스턴스 제한 해제

```yaml
# deploy.yml — SQLite 단일 작성자 제약이 사라지므로
--min-instances=1 --max-instances=10  # 또는 그 이상
```

## 인터페이스 계약

모든 메서드는 backend-agnostic 한 dict 를 주고받음. 컬럼 이름은 SQLite 스키마와 동일.

| 메서드 | 동작 | atomic 요구 |
|---|---|---|
| `init()` | 스키마/인덱스 준비 | — |
| `get_or_create_oauth_user(p, pid, email, name)` | 기존 있으면 업데이트, 없으면 생성 | ✅ |
| `get_user(user_id)` | dict 또는 None | — |
| `get_user_by_stripe_customer(cust)` | dict 또는 None | — |
| `consume_quota(user_id, cap)` | (allowed, remaining, reset_date), 새 날 리셋 | ✅ |
| `peek_quota(user_id, cap)` | (used, cap, remaining, reset_date) | — |
| `set_subscription(user_id, ...)` | 구독 6필드 upsert | — |
| `clear_subscription(user_id)` | status=canceled, period_end=NULL | — |
| `delete_user(user_id)` | 행 삭제 | — |
| `stats_snapshot(today, now, cap)` | 집계 dict — admin 대시보드용 | — |
| `reset_all()` | 전체 삭제 — 테스트 전용 | — |

`consume_quota` 만 atomic 이 필수 — 동시 호출에서 cap 초과 방지.
SQLite 는 `with conn:` 트랜잭션, Firestore 는 `@firestore.transactional` 사용.

## 백엔드 교체 시 영향 없는 코드

`users.py` import 만 하는 모든 모듈:
- `chatbot.py` — consume_quota, peek_quota, has_active_subscription, delete_user, ...
- `auth.py` — get_or_create_oauth_user, get_user
- `billing.py` — get_user_by_stripe_customer, set_subscription, clear_subscription
- `admin.py` — stats_snapshot, reset_all

직접 SQL 을 쓰던 곳은 모두 인터페이스로 옮겨졌으므로 백엔드 교체에 영향 X.
