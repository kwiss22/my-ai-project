"""실제 한국인과의 회화 세션 — 예약제.

AI 캐릭터 대화(chatbot.py `/chat`)와 완전히 분리된 서비스다. 공유하는 것은
로그인 세션뿐이고, 캐릭터 프롬프트·일일 quota·구독 게이트와 얽히지 않는다.
AI 쪽 코드 경로는 이 모듈 때문에 바뀌지 않는다.

'실시간 매칭' 이 아니라 '예약' 인 이유 두 가지:
  - Cloud Run `max-instances=1` + gunicorn 기본 워커 1개. 접속을 계속 붙잡는
    양방향 채팅을 올리면 한 명이 나머지 전원을 큐에 세운다. 실시간으로 가려면
    SQLite → Firestore 이전이 선행돼야 한다.
  - 공급이 사람 시간이라 한계비용이 실재한다. 정액 구독에 '무제한' 으로 녹이면
    헤비 유저에서 마진이 깨진다. 그래서 횟수로 끊는 예약 단위가 기본.

v1 은 결제를 붙이지 않는다. 목적이 수요 검증이고, 건당 결제는 현재 PayPal
설정(구독 전용 플랜)에 없는 경로라 별도 작업이다. 요청이 쌓이면 붙인다.

운영 흐름:
  requested  학습자가 희망 시각으로 요청        (POST /human/book)
  confirmed  운영자가 확정 + 통화 링크 기입      (POST /admin/human-session)
  done       세션 종료                          (POST /admin/human-session)
  cancelled  학습자 취소 또는 운영자 반려        (POST /human/cancel)

ENV:
  HUMAN_SESSIONS_ENABLED=false   기능 전체 off (랜딩·앱에서 숨김)
  HUMAN_SESSION_PARTNERS         파트너 명단 JSON. 비우면 아래 기본값.
  HUMAN_SESSION_DURATION_MIN     세션 길이 (기본 25)
  HUMAN_SESSION_PRICE_USD        표시용 가격. '0' 이면 무료 체험으로 표기.
  HUMAN_SESSION_REQUIRES_PAID    true 면 구독자만 예약 가능 (기본 false)
"""
import json
import os
import time
from datetime import datetime, timezone

from flask import request, jsonify

from users import (
    create_human_session,
    list_human_sessions,
    cancel_human_session,
    pending_human_sessions,
    update_human_session,
    is_paid,
)
from auth import current_user
from events import log_event


# 기본 off. 실제 파트너가 HUMAN_SESSION_PARTNERS 로 등록되기 전에는 켜면 안 된다 —
# 아래 _DEFAULT_PARTNERS 는 UI 렌더용 자리표시자라서, 켜두면 존재하지 않는
# 사람과의 예약을 받게 된다. 파트너 등록 후 env 로 true 를 주고 켠다.
HUMAN_SESSIONS_ENABLED = os.getenv('HUMAN_SESSIONS_ENABLED', 'false').lower() == 'true'
HUMAN_SESSION_DURATION_MIN = int(os.getenv('HUMAN_SESSION_DURATION_MIN', '25'))
HUMAN_SESSION_PRICE_USD = os.getenv('HUMAN_SESSION_PRICE_USD', '0')
HUMAN_SESSION_REQUIRES_PAID = os.getenv('HUMAN_SESSION_REQUIRES_PAID', 'false').lower() == 'true'

# 성인 자기확인 기준. 처음 보는 성인과 1:1 로 붙는 서비스라 AI 쪽과 달리 게이트가 필요하다.
HUMAN_SESSION_MIN_AGE = 18

# 예약 가능 창 — 너무 임박하면 파트너가 대응 못 하고, 너무 멀면 노쇼가 늘어난다.
_MIN_LEAD_SEC = 2 * 3600
_MAX_LEAD_SEC = 30 * 86400

# 파트너 명단.
# 공개되는 필드만 둔다 — 실명·연락처·SNS·이메일은 절대 넣지 않는다. 통화 링크는
# 확정 시 운영자가 세션 행에 넣고, 파트너의 개인 정보는 학습자에게 가지 않는다.
# 실제 사람을 추가할 때는 HUMAN_SESSION_PARTNERS 환경변수(JSON)로 주입해서
# 코드 저장소에 개인 정보가 남지 않게 한다.
_DEFAULT_PARTNERS = [
    {
        'id': 'partner1',
        'name': 'Jun',                 # 활동명. 실명 아님.
        'city': 'Seoul',
        'age_band': '20s',
        'speaks': ['ko', 'en'],
        'topics': ['daily life', 'K-pop', 'food in Seoul'],
        'intro_en': 'Hi! I am a native Korean speaker from Seoul. '
                    'We can just chat — no textbook, no pressure.',
        'intro_ko': '서울 사는 한국인이에요. 교재 없이 편하게 수다 떨어요.',
        'photo': None,                 # 정적 파일 경로. 없으면 UI 가 이니셜로 대체.
    },
]


def _load_partners():
    """ENV JSON 우선, 실패하면 기본값. 배포 중 JSON 오타로 기능이 죽지 않게 가드."""
    raw = os.getenv('HUMAN_SESSION_PARTNERS', '').strip()
    if not raw:
        return _DEFAULT_PARTNERS
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and parsed:
            return parsed
    except (ValueError, TypeError):
        log_event('warn', 'human.partners_parse_failed',
                  'HUMAN_SESSION_PARTNERS JSON 파싱 실패 — 기본 명단 사용')
    return _DEFAULT_PARTNERS


HUMAN_PARTNERS = {p['id']: p for p in _load_partners()}


def human_sessions_enabled():
    return bool(HUMAN_SESSIONS_ENABLED and HUMAN_PARTNERS)


# 학습자에게 보여줄 규칙. 파트너가 경계를 설정할 때 가리킬 수 있는 문서가 있어야
# 운영이 버틴다 — 이런 서비스의 1번 운영 문제가 '범위 흐려짐' 이다.
SESSION_POLICY = {
    'min_age': HUMAN_SESSION_MIN_AGE,
    'scope': [
        'Korean conversation practice and friendly chat.',
        'Your partner may end the session if conversation becomes sexual, '
        'abusive, or asks for personal contact details.',
        'Keep contact inside the platform — no phone numbers, KakaoTalk IDs, '
        'or social media exchanges.',
        'This is a language and conversation service, not a dating or '
        'matchmaking service.',
    ],
}


def _public_partner(p):
    """외부 노출용 사영 — 화이트리스트 방식. 명단에 민감 필드가 섞여도 새지 않는다."""
    return {
        'id': p.get('id'),
        'name': p.get('name'),
        'city': p.get('city'),
        'age_band': p.get('age_band'),
        'speaks': p.get('speaks') or [],
        'topics': p.get('topics') or [],
        'intro_en': p.get('intro_en'),
        'intro_ko': p.get('intro_ko'),
        'photo': p.get('photo'),
    }


def _parse_slot(value):
    """unix sec(int) 또는 ISO 8601 문자열 → unix sec. 실패 시 None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        # 'Z' 는 fromisoformat 이 못 읽는다(3.11 미만 호환).
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _session_view(row):
    """예약 1건의 응답 형태. 확정 전에는 통화 링크를 내보내지 않는다."""
    partner = HUMAN_PARTNERS.get(row.get('partner_id')) or {}
    confirmed = row.get('status') == 'confirmed'
    return {
        'id': row.get('id'),
        'partner': _public_partner(partner) if partner else {'id': row.get('partner_id')},
        'slot_start': row.get('slot_start'),
        'duration_min': row.get('duration_min'),
        'status': row.get('status'),
        'note': row.get('note'),
        'meeting_url': row.get('meeting_url') if confirmed else None,
        'created_at': row.get('created_at'),
    }


# ---- 공개: 파트너 목록 -------------------------------------------------------

def partners():
    """로그인 없이 볼 수 있다 — 가입 전에 뭘 제공하는지 보여줘야 전환이 생긴다."""
    return jsonify({
        'enabled': human_sessions_enabled(),
        'partners': [_public_partner(p) for p in HUMAN_PARTNERS.values()],
        'duration_min': HUMAN_SESSION_DURATION_MIN,
        'price_usd': HUMAN_SESSION_PRICE_USD,
        'requires_paid': HUMAN_SESSION_REQUIRES_PAID,
        'policy': SESSION_POLICY,
        'lead_time': {'min_hours': _MIN_LEAD_SEC // 3600,
                      'max_days': _MAX_LEAD_SEC // 86400},
    })


# ---- 예약 ------------------------------------------------------------------

def book():
    """body: {partner_id, slot_start, note?, adult_confirmed}"""
    if not human_sessions_enabled():
        return jsonify({'error': 'This service is not available yet.'}), 503
    user = current_user()
    if not user:
        return jsonify({'error': '로그인이 필요해요.', 'paywall': 'login'}), 401
    if HUMAN_SESSION_REQUIRES_PAID and not is_paid(user):
        return jsonify({'error': '구독하면 예약할 수 있어요.', 'paywall': 'human_session'}), 402

    data = request.get_json(silent=True) or {}

    partner_id = (data.get('partner_id') or '').strip()
    if partner_id not in HUMAN_PARTNERS:
        return jsonify({'error': 'unknown partner_id'}), 400

    # 성인 확인은 서버에서 막는다. 클라이언트 체크박스만으로는 확인했다고 할 수 없다.
    if not data.get('adult_confirmed'):
        return jsonify({
            'error': f'You must confirm you are {HUMAN_SESSION_MIN_AGE} or older.',
            'reason': 'adult_required',
        }), 400

    slot = _parse_slot(data.get('slot_start'))
    if slot is None:
        return jsonify({'error': 'slot_start must be unix seconds or ISO 8601'}), 400
    now = int(time.time())
    if slot < now + _MIN_LEAD_SEC:
        return jsonify({'error': f'Pick a time at least {_MIN_LEAD_SEC // 3600} hours from now.',
                        'reason': 'too_soon'}), 400
    if slot > now + _MAX_LEAD_SEC:
        return jsonify({'error': f'Pick a time within {_MAX_LEAD_SEC // 86400} days.',
                        'reason': 'too_far'}), 400

    note = (data.get('note') or '').strip()[:500] or None

    row, err = create_human_session(
        user['user_id'], partner_id, slot,
        duration_min=HUMAN_SESSION_DURATION_MIN,
        note=note, adult_confirmed=True,
    )
    if err == 'duplicate':
        return jsonify({'error': 'You already have a booking at that time.',
                        'reason': 'duplicate'}), 409
    if not row:
        return jsonify({'error': 'Could not create booking.', 'reason': err or 'unknown'}), 400

    # 퍼널 추적 — 이 기능의 수요 검증이 전부 이 이벤트에 달려 있다.
    log_event('info', 'human.session_requested', '실사람 세션 예약 요청',
              user_id=user['user_id'], partner_id=partner_id,
              slot_start=slot, session_id=row.get('id'))
    return jsonify({'ok': True, 'session': _session_view(row)}), 201


def bookings():
    user = current_user()
    if not user:
        return jsonify({'error': '로그인이 필요해요.', 'paywall': 'login'}), 401
    rows = list_human_sessions(user['user_id'])
    return jsonify({'sessions': [_session_view(r) for r in rows]})


def cancel():
    """body: {session_id}"""
    user = current_user()
    if not user:
        return jsonify({'error': '로그인이 필요해요.', 'paywall': 'login'}), 401
    data = request.get_json(silent=True) or {}
    try:
        sid = int(data.get('session_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'session_id must be int'}), 400
    ok = cancel_human_session(user['user_id'], sid)
    if ok:
        log_event('info', 'human.session_cancelled', '학습자가 세션 취소',
                  user_id=user['user_id'], session_id=sid)
    return jsonify({'ok': ok})


# ---- 운영자 ----------------------------------------------------------------

def admin_sessions():
    from admin import _require_admin
    ok, err = _require_admin()
    if not ok:
        return err
    rows = pending_human_sessions()
    # 운영자 화면은 누가 신청했는지 알아야 하므로 user_id 를 남긴다.
    out = []
    for r in rows:
        view = _session_view(r)
        view['user_id'] = r.get('user_id')
        view['meeting_url'] = r.get('meeting_url')
        out.append(view)
    return jsonify({'sessions': out})


def admin_update():
    """body: {session_id, status?, meeting_url?}"""
    from admin import _require_admin
    ok, err = _require_admin()
    if not ok:
        return err
    data = request.get_json(silent=True) or {}
    try:
        sid = int(data.get('session_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'session_id must be int'}), 400
    status = data.get('status')
    if status is not None and status not in ('requested', 'confirmed', 'done', 'cancelled'):
        return jsonify({'error': 'invalid status'}), 400
    meeting_url = data.get('meeting_url')
    row = update_human_session(sid, status=status, meeting_url=meeting_url)
    if not row:
        return jsonify({'error': 'not found'}), 404
    log_event('info', 'human.session_updated', '운영자가 세션 상태 변경',
              session_id=sid, status=status)
    view = _session_view(row)
    view['meeting_url'] = row.get('meeting_url')
    return jsonify({'ok': True, 'session': view})
