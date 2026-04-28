# K-Dating Chat - 현재 구현 상태

> 마지막 업데이트: 2026-03-30

---

## 캐릭터

| 캐릭터 | 설정 | 특이사항 |
|--------|------|----------|
| 지우 (Jiwoo) | 이대 경영학과 3학년, 22세, 강남 카페 알바 | 존댓말 → 친해지면 반말 전환 |
| 현우 (Hyun-woo) | 홍대 실용음악과 2학년, 23세, K-pop 연습생 4년차 | 항상 반말, 직진남 스타일 |

---

## 구현된 기능

### 핵심 채팅
- [x] Gemini API (`gemini-flash-latest`) 기반 AI 응답
- [x] 세션별 대화 히스토리 유지 (chat_session 내부 관리)
- [x] 카카오톡 스타일 UI (말풍선, 배경색, 애니메이션)
- [x] 온라인 상태 표시 (초록 점, pulse 애니메이션)
- [x] 읽음 표시 ("1" → 읽음 시 회색)

### 온보딩
- [x] 닉네임 입력 (선택)
- [x] 한국어 레벨 선택 (완전 초보 / 조금 알아요 / 어느 정도)
- [x] 관심사 선택 (K-드라마, K-pop, 여행, 음식, 문화, 연애)
- [x] 캐릭터 선택 (지우 / 현우)
- [x] 유저 프로필 → 시스템 프롬프트에 반영

### TTS (음성)
- [x] Azure Speech Service 한국어 TTS
  - 지우: `ko-KR-SunHiNeural` (여성)
  - 현우: `ko-KR-InJoonNeural` (남성)
- [x] **속삭임 모드**: "속삭여줘" 요청 시 낮은 볼륨 + 느린 속도 SSML 처리
- [x] 마크다운, URL, 이모지 자동 제거 후 TTS

### 번역
- [x] Google Cloud Translation API (한국어 → 영어)
- [x] 메시지별 번역 버튼

### 스티커
- [x] 카카오톡 스타일 스티커 피커 UI
- [x] AI가 응답에 스티커 태그 포함 (`[sticker:id]`)
- [x] 유저도 스티커 전송 가능
- [x] 지우 스티커: happy, love, shy, coffee, sad, cheer, wink, hug (PNG)
- [x] 현우 스티커: heart, wink, kiss, angry, cry, surprise, laugh, shy, think, cheer (PNG)

### 단어장
- [x] AI 응답에서 어려운 단어 자동 감지 (Gemini로 추출, 최대 3개)
- [x] 단어 저장 (localStorage)
- [x] 단어장 모달 (저장된 단어 목록)
- [x] **단어 퀴즈**: 저장된 단어 → 4지선다 퀴즈, 점수 표시

### 학습 보조
- [x] 문법 힌트 모드 (토글): 한국어 오류 시 캐릭터가 자연스럽게 교정
- [x] 단어 자동 감지 토글 (기본 ON)
- [x] 오늘의 운세: 생년월일 입력 → 별자리 + 띠 + MBTI 기반 맞춤 운세

### 데일리 미션
- [x] 날짜 기반 10가지 미션 (매일 다름)
- [x] 채팅 화면 상단 배너로 표시
- [x] 미션 예시: "한국어로 메시지 하나 보내기", "드라마 추천받기" 등

### 알림 (Push Notification)
- [x] Firebase Cloud Messaging (FCM) 연동
- [x] 알림 허용 배너 UI
- [x] 예약 알림 발송 API (`/send-scheduled-notifications`)
  - 시간대별 메시지: morning / afternoon / evening / night / fortune
  - 캐릭터별 다른 메시지

### 수익화
- [x] Buy Me a Coffee 플로팅 버튼
- [x] 현우 프롬프트에 커피($3) / 치킨($10) 링크 자연스럽게 삽입
  - 커피: 일반 응원 메시지와 함께
  - 치킨: 구매 시 속삭임 + 비밀 사진 리액션

### 데이터 저장
- [x] Google Cloud Datastore - 대화 내용 저장
- [x] Google Sheets - 채팅 로그 기록 (`Kdate_Chat_Log`)
- [x] 파일 기반 히스토리 (`chat_history.py`)

### 기타
- [x] 다국어 UI (한국어 / 영어 전환, i18n)
- [x] SEO 메타태그 (Open Graph, Twitter Card)
- [x] GCP Cloud Run 배포 (`kdating-chat-515513943326.asia-northeast3.run.app`)

---

## API 엔드포인트

| 메서드 | 경로 | 기능 |
|--------|------|------|
| GET | `/` | 메인 페이지 |
| POST | `/select-character` | 캐릭터 + 온보딩 프로필 설정 |
| POST | `/chat` | AI 채팅 응답 |
| POST | `/new-session` | 새 대화 시작 |
| GET | `/sessions` | 세션 목록 |
| GET | `/sessions/<date>` | 날짜별 세션 |
| POST | `/tts` | Azure TTS 음성 생성 |
| POST | `/translate` | 한국어 → 영어 번역 |
| POST | `/register-push` | FCM 토큰 등록 |
| POST | `/send-scheduled-notifications` | 예약 알림 발송 |
| GET | `/daily-mission` | 오늘의 미션 |

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| Backend | Flask (Python 3.11) |
| AI | Google Gemini API (`gemini-flash-latest`) |
| TTS | Azure Cognitive Services Speech |
| 번역 | Google Cloud Translation v2 |
| DB | Google Cloud Datastore |
| 로그 | Google Sheets (gspread) |
| Push | Firebase Cloud Messaging |
| 배포 | Google Cloud Run |
| Frontend | Vanilla JS + CSS (카카오톡 스타일) |

---

## 미구현 / 향후 작업

- [ ] 미니게임 (제안 예정)
- [ ] 음성 입력 (STT)
- [ ] 대화 기록 UI (날짜별 히스토리 보기)
- [ ] 호감도 시스템 (데이트 진행도)
- [ ] 데이트 시나리오 (장소별 특별 대화)
