"""Critical 이벤트 알림 — SMTP 이메일 + Slack incoming webhook.

비동기 (daemon thread) 발송으로 request 경로를 막지 않음.
같은 kind 의 알림은 ALERT_DEDUP_SECONDS 내 한 번만 발송 (반복 공격·결제 실패
폭주 시 알림 폭주 방지).

ENV (모두 선택, 미설정 시 no-op):
  ALERT_MIN_SEVERITY        'critical' (기본) / 'error' / 'warn' / 'info'
  ALERT_DEDUP_SECONDS       300 (기본). 같은 kind 의 알림 묶기 윈도.
  ALERT_SMTP_HOST           예: smtp.gmail.com
  ALERT_SMTP_PORT           587 (기본, STARTTLS)
  ALERT_SMTP_USER           발신 이메일
  ALERT_SMTP_PASSWORD       앱 비밀번호 (Gmail 2FA 계정의 16자리)
  ALERT_SMTP_FROM           (생략 시 ALERT_SMTP_USER)
  ALERT_EMAIL_TO            수신 이메일 (쉼표 구분)
  ALERT_SLACK_WEBHOOK_URL   Slack incoming webhook URL

또한 모니터링/테스트 hook:
  ALERT_TEST_SINK           '1' 이면 send 함수가 호출되지 않고
                            in-memory list 에 적재. /admin/alerts-test 로 조회.
"""
import json
import os
import smtplib
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage


SMTP_HOST = os.getenv('ALERT_SMTP_HOST', '')
SMTP_PORT = int(os.getenv('ALERT_SMTP_PORT', '587') or '587')
SMTP_USER = os.getenv('ALERT_SMTP_USER', '')
SMTP_PASSWORD = os.getenv('ALERT_SMTP_PASSWORD', '')
SMTP_FROM = os.getenv('ALERT_SMTP_FROM', '') or SMTP_USER
EMAIL_TO = [e.strip() for e in (os.getenv('ALERT_EMAIL_TO', '') or '').split(',') if e.strip()]
SLACK_URL = os.getenv('ALERT_SLACK_WEBHOOK_URL', '')

DEDUP_SECONDS = int(os.getenv('ALERT_DEDUP_SECONDS', '300') or '300')
MIN_SEVERITY = os.getenv('ALERT_MIN_SEVERITY', 'critical').lower()

TEST_SINK = os.getenv('ALERT_TEST_SINK') == '1'

_SEV_RANK = {'info': 0, 'warn': 1, 'error': 2, 'critical': 3}
_DEDUP_LOCK = threading.Lock()
_last_sent_at = {}  # kind → unix ts

# 테스트용 메모리 sink (TEST_SINK 가 true 일 때만 사용)
_test_sink = []
_test_sink_lock = threading.Lock()


def smtp_enabled():
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and EMAIL_TO)


def slack_enabled():
    return bool(SLACK_URL)


def any_enabled():
    return TEST_SINK or smtp_enabled() or slack_enabled()


def _should_send(severity, kind):
    if not any_enabled():
        return False
    if _SEV_RANK.get(severity, 0) < _SEV_RANK.get(MIN_SEVERITY, 3):
        return False
    with _DEDUP_LOCK:
        now = time.time()
        last = _last_sent_at.get(kind, 0)
        if now - last < DEDUP_SECONDS:
            return False
        _last_sent_at[kind] = now
    return True


def _send_slack(severity, kind, message, context):
    emoji = {
        'critical': ':rotating_light:',
        'error':    ':warning:',
        'warn':     ':bell:',
        'info':     ':information_source:',
    }.get(severity, ':grey_exclamation:')
    text = f'{emoji} *{severity.upper()}* `{kind}`\n{message}'
    if context:
        try:
            ctx_json = json.dumps(context, ensure_ascii=False, indent=2)[:1500]
            text += f'\n```\n{ctx_json}\n```'
        except (TypeError, ValueError):
            pass
    body = json.dumps({'text': text}).encode('utf-8')
    req = urllib.request.Request(
        SLACK_URL, data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except (urllib.error.URLError, OSError) as e:
        print(f'[ALERT] slack send failed kind={kind}: {str(e)[:160]}')


def _send_email(severity, kind, message, context):
    subject = f'[{severity.upper()}] K-Dating Chat: {kind}'
    body_lines = [
        f'Severity: {severity}',
        f'Kind:     {kind}',
        f'Message:  {message}',
        '',
        'Context:',
        json.dumps(context, ensure_ascii=False, indent=2),
    ]
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SMTP_FROM
    msg['To'] = ', '.join(EMAIL_TO)
    msg.set_content('\n'.join(body_lines))
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as s:
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        print(f'[ALERT] smtp send failed kind={kind}: {str(e)[:160]}')


def _dispatch(severity, kind, message, context):
    """daemon thread 안에서 실행. 채널 각각 best-effort — 한쪽 실패해도 다른쪽 시도.

    TEST_SINK 는 추가 sink — 실 채널을 차단하지 않음 (운영 중 실수로 켜놨을 때
    실 알림이 묵음 처리되는 위험 회피).
    """
    if TEST_SINK:
        with _test_sink_lock:
            _test_sink.append({
                'severity': severity, 'kind': kind,
                'message': message, 'context': context,
                'ts': time.time(),
            })
    if slack_enabled():
        _send_slack(severity, kind, message, context)
    if smtp_enabled():
        _send_email(severity, kind, message, context)


def notify(severity, kind, message='', **context):
    """events.log_event 가 호출. severity threshold + dedup 통과 시 비동기 발송."""
    if not _should_send(severity, kind):
        return
    t = threading.Thread(target=_dispatch, args=(severity, kind, message, context), daemon=True)
    t.start()


# ---- 테스트 헬퍼 ------------------------------------------------------------

def get_test_sink():
    """ALERT_TEST_SINK=1 일 때만. /admin/alerts-test 에서 호출."""
    with _test_sink_lock:
        return list(_test_sink)


def clear_test_sink():
    with _test_sink_lock:
        _test_sink.clear()


def reset_dedup():
    """테스트 전용. 운영 코드에서 호출 X."""
    with _DEDUP_LOCK:
        _last_sent_at.clear()
