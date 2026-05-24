"""구조화된 이벤트 로그.

JSONL 파일에 append. 운영자가 `tail -f` 로 실시간 모니터링, 또는
/admin/events 로 조회. 외부 의존 없음 — SMTP·Slack 알림은 별도 키 필요해서
다음 단계에서 추가.

이벤트 종류 (kind, 점 구분):
  subscription.activated      구독 활성 (trial 또는 active 진입)
  subscription.trial_started  trial 시작
  subscription.canceled       완전 해지
  subscription.cancel_scheduled  cancel_at_period_end 표시
  payment.failed              결제 실패 (invoice.payment_failed)
  webhook.signature_invalid   Stripe webhook 위조 시도
  account.deleted             계정 셀프 삭제
  http.5xx                    서버 에러 응답
  vendor.gemini_failed        Gemini API 에러
  vendor.azure_failed         Azure (TTS/STT) 에러
  ratelimit.hit               비정상 빈도로 차단 (옵션, 잠재적으로 시끄러움)

심각도 (severity):
  info     운영 활동 (구독 활성 등)
  warn     주의 (해지·결제 실패·trial 종료 임박)
  error    서버측 오류 (5xx, vendor failure)
  critical 보안·금전 — 즉시 확인 (webhook 위조, 반복 결제 실패 등)

ENV:
  EVENTS_LOG_PATH      events.jsonl 위치 (기본: 모듈 옆 events.jsonl)
  EVENTS_KEEP_LINES    파일이 10MB 넘으면 최근 N줄만 보존 (기본 10000)
"""
import os
import json
import threading
from datetime import datetime, timezone

EVENTS_LOG_PATH = os.getenv(
    'EVENTS_LOG_PATH',
    os.path.join(os.path.dirname(__file__), 'events.jsonl'),
)
KEEP_LINES = int(os.getenv('EVENTS_KEEP_LINES', '10000'))
ROTATE_AT_BYTES = 10 * 1024 * 1024  # 10MB

_lock = threading.Lock()
SEVERITIES = ('info', 'warn', 'error', 'critical')


def log_event(severity, kind, message='', **context):
    """append-only JSONL 한 줄 기록. 동시성 안전 (file lock).

    context 의 값은 JSON 직렬화 가능한 것만 — 직렬화 실패 시 str() 잘라서 저장.
    """
    if severity not in SEVERITIES:
        severity = 'info'
    rec = {
        'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        'severity': severity,
        'kind': str(kind)[:64],
        'message': str(message)[:500],
    }
    for k, v in context.items():
        try:
            json.dumps(v, ensure_ascii=False)
            rec[k] = v
        except (TypeError, ValueError):
            rec[k] = str(v)[:200]
    line = json.dumps(rec, ensure_ascii=False) + '\n'
    with _lock:
        try:
            with open(EVENTS_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(line)
        except (IOError, OSError) as e:
            print(f'[EVENTS] write failed kind={kind}: {e}')
            return
        try:
            if os.path.getsize(EVENTS_LOG_PATH) > ROTATE_AT_BYTES:
                _truncate_locked()
        except OSError:
            pass


def _truncate_locked():
    """파일이 너무 크면 최근 KEEP_LINES 줄만 보존. _lock 보유 중 호출."""
    try:
        with open(EVENTS_LOG_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        keep = lines[-KEEP_LINES:]
        with open(EVENTS_LOG_PATH, 'w', encoding='utf-8') as f:
            f.writelines(keep)
    except (IOError, OSError) as e:
        print(f'[EVENTS] truncate failed: {e}')


def read_recent(limit=100, severity=None, kind=None, kind_prefix=None):
    """최근 이벤트 N개 (newest first). 필터 가능."""
    try:
        with open(EVENTS_LOG_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    out = []
    for line in reversed(lines):
        if len(out) >= limit:
            break
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if severity and rec.get('severity') != severity:
            continue
        if kind and rec.get('kind') != kind:
            continue
        if kind_prefix and not str(rec.get('kind', '')).startswith(kind_prefix):
            continue
        out.append(rec)
    return out


def summary_last_7d():
    """최근 7일 severity / kind 별 카운트. admin dashboard 용."""
    cutoff = datetime.now(timezone.utc).timestamp() - 7 * 86400
    by_sev = {s: 0 for s in SEVERITIES}
    by_kind = {}
    try:
        with open(EVENTS_LOG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ts = rec.get('ts', '')
                try:
                    # 'YYYY-MM-DDTHH:MM:SS.ffffffZ' 또는 'YYYY-MM-DDTHH:MM:SSZ'
                    dt = datetime.strptime(ts[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
                if dt.timestamp() < cutoff:
                    continue
                sev = rec.get('severity', 'info')
                by_sev[sev] = by_sev.get(sev, 0) + 1
                k = rec.get('kind', 'unknown')
                by_kind[k] = by_kind.get(k, 0) + 1
    except FileNotFoundError:
        pass
    return {'by_severity': by_sev, 'by_kind': by_kind}
