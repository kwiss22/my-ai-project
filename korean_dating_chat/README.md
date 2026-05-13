# 💕 K-Dating Chat - 한국어 학습 데이팅 챗봇

외국인이 한국인 남자친구/여자친구와 대화하면서 한국어를 배우는 데이팅 시뮬레이션 챗봇입니다.

## ✨ 특징

- 🎭 **캐릭터 선택**: 민준 (남자친구) 또는 지우 (여자친구)
- 💬 **카카오톡 스타일 UI**: 친숙한 채팅 인터페이스
- 🇰🇷 **한국어로 대화**: AI가 한국어로만 응답
- 🌐 **영어 번역**: 한국어 → 영어 번역 버튼 제공
- 🔊 **한국어 TTS**: Google Cloud TTS로 자연스러운 한국어 음성
- 💾 **대화 저장**: Datastore에 대화 기록 저장

## 🚀 로컬 실행

```bash
cd korean_dating_chat
python chatbot.py
```

브라우저에서 http://localhost:8080 접속

## 📦 배포 (Cloud Run)

### 자동 배포 (권장)
`main` 브랜치에 푸시되면 GitHub Actions가 자동으로 Cloud Run에 배포합니다.
워크플로우: `.github/workflows/deploy.yml` (설정 가이드는 `.github/workflows/README.md`)

### 수동 배포
```bash
cd korean_dating_chat
./deploy.sh
```

내부적으로 실행되는 명령:
```bash
gcloud run deploy kdating-chat \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated
```

배포 후 URL: `https://kdating-chat-515513943326.asia-northeast3.run.app`

전제 조건:
- `gcloud` CLI 설치 및 인증 완료 (`gcloud auth login`)
- 프로젝트 설정 (`gcloud config set project <PROJECT_ID>`)
- `GEMINI_API_KEY` 등 환경 변수는 Cloud Run 서비스에 이미 등록되어 있어야 함
  (source-deploy는 기존 서비스의 env vars를 보존함)

문제 시 Cloud Run 콘솔에서 이전 revision으로 traffic 100% rollback 가능.

## 🎮 사용 방법

1. **캐릭터 선택**: 민준 또는 지우 선택
2. **대화 시작**: 영어나 한국어로 메시지 입력
3. **번역 보기**: AI 메시지 하단의 "🌐 English" 클릭
4. **캐릭터 변경**: 우측 상단 "캐릭터 변경" 버튼

## 📁 프로젝트 구조

```
korean_dating_chat/
├── chatbot.py          # Flask 백엔드
├── chat_history.py     # 대화 히스토리 관리
├── templates/
│   └── index.html      # 카카오톡 스타일 UI
├── static/             # 정적 파일
├── requirements.txt    # 의존성
├── app.yaml           # App Engine 설정 (레거시)
├── Dockerfile         # Cloud Run 컨테이너 정의
├── deploy.sh          # Cloud Run 배포 스크립트
└── .env               # 환경 변수
```

## 🔧 기술 스택

- **Backend**: Flask, Python 3.11
- **AI**: Google Vertex AI (Gemini 1.5 Flash)
- **TTS**: Google Cloud Text-to-Speech
- **Translation**: Google Cloud Translation API
- **Database**: Google Cloud Datastore
- **Deployment**: Google Cloud Run (asia-northeast3)

## 🎭 캐릭터 정보

### 민준 (Minjun) 👨
- 28세 소프트웨어 개발자
- 서울 거주
- 친근하고 유머러스한 성격

### 지우 (Jiwoo) 👩
- 25세 카페 직원
- 강남 카페 근무
- 밝고 상냥한 성격

## 📝 주요 변경사항 (vs Cindy 영어 교사)

| 항목 | Cindy | K-Dating Chat |
|------|-------|---------------|
| 응답 언어 | 영어만 | 한국어만 |
| 번역 방향 | 영어 → 한국어 | 한국어 → 영어 |
| UI 스타일 | 교육용 | 카카오톡 스타일 |
| 게이미피케이션 | 스테이지, 별 | 없음 (단순 채팅) |
| 캐릭터 | Cindy (선생님) | 민준/지우 (연인) |
| 컨셉 | 영어 학습 | 데이팅 + 한국어 학습 |

## 🎯 향후 개선 사항

- [ ] 대화 기록 UI 추가
- [ ] 음성 인식 추가 (한국어/영어)
- [ ] 프로필 이미지 추가
- [ ] 감정 표현 개선
- [ ] 데이트 시나리오 추가

---

Made with ❤️ for Korean language learners
