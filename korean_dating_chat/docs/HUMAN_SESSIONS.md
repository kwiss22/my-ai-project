# 실제 한국인 회화 세션 (예약제)

AI 캐릭터 대화와 **별개 서비스**. 코드는 `human.py` + `users.py` 의 `human_sessions`
테이블 + `templates/index.html` 의 예약 모달. AI 채팅 경로(`/chat`)는 이 기능과
상태를 공유하지 않는다.

## 왜 실시간이 아니라 예약제인가

두 제약이 실시간을 막는다. 둘 다 풀지 않으면 예약제가 유일한 선택이다.

1. **Cloud Run `max-instances=1` + gunicorn 워커 1개.**
   `Dockerfile` 의 `CMD exec gunicorn -b :$PORT chatbot:app` 에 `--workers`·
   `--threads` 가 없어 기본값(sync 워커 1개)으로 돈다. 접속을 계속 붙잡는 양방향
   채팅을 올리면 한 명이 나머지 전원을 큐에 세운다. 실시간으로 가려면 SQLite →
   Firestore 이전 + `max-instances` 해제가 선행돼야 한다.
2. **공급이 사람 시간이라 한계비용이 실재한다.** 정액 구독에 '무제한' 으로 녹이면
   헤비 유저에서 마진이 깨진다(Cambly 가 분 단위 요금제를, italki 가 건당 결제를
   쓰는 이유). 그래서 세션을 횟수로 끊는다.

## 상태 흐름

```
requested  학습자가 희망 시각으로 요청        POST /human/book
confirmed  운영자가 확정 + 통화 링크 기입      POST /admin/human-session
done       세션 종료                          POST /admin/human-session
cancelled  학습자 취소 또는 운영자 반려        POST /human/cancel  또는 위와 동일
```

`meeting_url` 은 **status 가 `confirmed` 일 때만** 학습자에게 내려간다
(`human.py` 의 `_session_view`).

## 파트너 등록

개인 정보를 저장소에 남기지 않기 위해 **환경변수(JSON)로 주입**한다.
`human.py` 의 `_DEFAULT_PARTNERS` 는 UI 가 렌더될 수 있게 둔 자리표시자다.

```bash
PARTNERS='[
  {"id":"jun","name":"Jun","city":"Seoul","age_band":"20s",
   "speaks":["ko","en"],"topics":["daily life","K-pop"],
   "intro_en":"Hi! I am from Seoul. We can just chat.",
   "intro_ko":"서울 살아요. 편하게 수다 떨어요.",
   "photo":"/static/img/partners/jun.jpg"}
]'
gcloud run services update kdating-chat --region=asia-northeast3 \
    --update-env-vars="HUMAN_SESSION_PARTNERS=$PARTNERS"
```

공개 필드는 화이트리스트(`_public_partner`)로 걸러진다. 실명·연락처·SNS·이메일은
넣지 말 것 — 넣어도 `_public_partner` 가 안 내보내지만, 저장소/로그에 남는다.

JSON 이 깨지면 기능이 죽는 대신 기본 명단으로 폴백하고
`human.partners_parse_failed` 이벤트를 남긴다.

## ENV

| 변수 | 기본값 | 역할 |
|---|---|---|
| `HUMAN_SESSIONS_ENABLED` | **`false`** | 기본 off. 실제 파트너를 `HUMAN_SESSION_PARTNERS` 로 등록한 뒤 `true` 로 켠다. off 면 `/me` 의 `human_sessions` 가 false 가 되어 UI 진입 버튼이 숨고, 예약 API 는 503. |
| `HUMAN_SESSION_PARTNERS` | (없음) | 파트너 명단 JSON. 위 참조. |
| `HUMAN_SESSION_DURATION_MIN` | `25` | 세션 길이 |
| `HUMAN_SESSION_PRICE_USD` | `0` | 표시용. `0` 이면 무료 체험으로 표기. **결제는 아직 안 붙어 있다.** |
| `HUMAN_SESSION_REQUIRES_PAID` | `false` | `true` 면 구독자만 예약 가능 |

## API

| 메서드 | 경로 | 인증 | 비고 |
|---|---|---|---|
| GET | `/human/partners` | 없음 | 가입 전에도 보여야 전환이 생긴다 |
| POST | `/human/book` | 로그인 | 시간당 10회 제한. `adult_confirmed` 필수 |
| GET | `/human/bookings` | 로그인 | 내 예약 |
| POST | `/human/cancel` | 로그인 | 본인 예약만 |
| GET | `/admin/human-sessions` | 운영자 | 확정 대기 + 확정 목록 |
| POST | `/admin/human-session` | 운영자 | `{session_id, status?, meeting_url?}` |

### 예약 확정 (운영 작업)

```bash
# 1. 대기 목록
curl -s -b cookies.txt https://kdate.store/admin/human-sessions | jq

# 2. 확정 + 통화 링크
curl -s -b cookies.txt -X POST https://kdate.store/admin/human-session \
  -H 'Content-Type: application/json' \
  -d '{"session_id":1,"status":"confirmed","meeting_url":"https://meet.google.com/xxx-xxxx-xxx"}'
```

## 안전 — 지금 있는 것과 없는 것

**있는 것**

- **성인 자기확인이 저장 조건.** `adult_confirmed` 가 거짓이면 행을 만들지 않는다
  (`create_human_session`). UI 체크박스만으로는 "확인받았다" 고 말할 수 없다.
- **파트너 개인 정보 비노출.** 화이트리스트 사영 + 통화 링크는 운영자가 기입.
- **대화 규칙 문서화.** `human.py` 의 `SESSION_POLICY` 가 예약 화면에 표시된다.
  파트너가 경계를 설정할 때 가리킬 문서가 있어야 운영이 버틴다 — 이런 서비스의
  1번 운영 문제가 '범위 흐려짐' 이다.
- **언어 서비스로 명시.** 정책에 "not a dating or matchmaking service" 를 넣었다.
  연애·결혼 목적 연결로 보이면 「결혼중개업법」상 국제결혼중개업 등록 대상이 될
  수 있고, 결제사 정책에도 걸린다.

**아직 없는 것 (붙이기 전에 알아야 할 것)**

- **실연령 확인이 아니다.** 자기확인 체크박스다. 주 유입이 틱톡이라 사용자층이
  어리다는 점을 고려하면, 세션을 유료화·확대하기 전에 실제 게이트가 필요하다.
- **신고·차단 기능이 없다.** 저장소 전체에 모더레이션 코드가 없다. 파트너를 늘리기
  전에 최소한 세션 신고 경로가 있어야 한다.
- **결제 미연동.** 현재 PayPal 설정은 구독 플랜 전용이라 건당 결제 경로가 없다.
  수요가 확인되면 붙인다. 붙일 때 청구 명세를 **"한국어 회화 레슨"** 으로 둘 것 —
  결제사 정책상 가장 먼저 깨지는 지점이다.

## 퍼널 추적

`events.jsonl` 에 기록되는 이벤트:

- `human.session_requested` — 예약 요청 (수요 검증의 핵심 지표)
- `human.session_cancelled` — 학습자 취소
- `human.session_updated` — 운영자 상태 변경
- `human.partners_parse_failed` — 명단 JSON 오류

GA4: `human_session_requested`.

```bash
gcloud storage cp gs://kdate-data/events.jsonl - | grep '"human\.'
```
