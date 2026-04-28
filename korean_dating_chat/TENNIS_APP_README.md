# 🎾 테니스 자세 분석 앱

Google Gemini 1.5 Flash API를 활용한 AI 기반 테니스 자세 분석 애플리케이션입니다.

## 🌟 주요 기능

- 동영상 업로드 (MP4, MOV, AVI 등) 또는 유튜브 URL 입력
- Google Gemini 1.5 Flash를 통한 AI 자세 분석
- 자세의 **장점 1개**, **단점 1개**, **교정법 1개** 제공
- 직관적인 Streamlit UI
- 유튜브 동영상 자동 다운로드 및 분석
- **API 비용 절감을 위한 파일 크기 및 영상 길이 제한**
  - 최대 파일 크기: 100MB
  - 최대 영상 길이: 1분 (권장)

## 📋 사전 요구사항

1. Python 3.8 이상
2. Google Gemini API 키 ([발급 받기](https://ai.google.dev/))

## 🚀 설치 방법

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. API 키 설정

`.env` 파일을 생성하고 Gemini API 키를 추가하세요:

```
GEMINI_API_KEY=your_gemini_api_key_here
```

## 💻 실행 방법

```bash
streamlit run tennis_analysis_app.py
```

브라우저가 자동으로 열리며 `http://localhost:8501` 에서 앱에 접속할 수 있습니다.

## 📖 사용 방법

### 방법 1: 파일 업로드
1. **파일 업로드 탭** 선택
2. **동영상 업로드**: 파일 업로더에서 테니스 동영상을 선택
3. **분석 시작**: "분석 시작" 버튼 클릭
4. **결과 확인**: AI가 분석한 장점, 단점, 교정법을 확인

### 방법 2: 유튜브 URL
1. **유튜브 URL 탭** 선택
2. **URL 입력**: 유튜브 동영상 링크를 붙여넣기
3. **분석 시작**: "분석 시작" 버튼 클릭
4. **결과 확인**: AI가 분석한 장점, 단점, 교정법을 확인

## 🎯 분석 결과 예시

```
**장점:**
백핸드 스윙 시 체중 이동이 매우 자연스럽고, 라켓 헤드가 공을 향해 정확하게 움직입니다.

**단점:**
팔로우스루 동작에서 라켓이 너무 일찍 멈추어 파워가 손실되고 있습니다.

**교정법:**
스윙을 마친 후 라켓을 반대편 어깨까지 완전히 끌어올리는 연습을 해보세요.
매일 10분씩 거울을 보며 느린 동작으로 팔로우스루를 연습하면 효과적입니다.
```

## 🔧 기술 스택

- **Frontend**: Streamlit
- **AI Model**: Google Gemini 1.5 Flash
- **Video Download**: yt-dlp
- **Language**: Python 3.x

## ⚙️ 업로드 제한 변경

파일 크기와 영상 길이 제한을 변경하려면 [tennis_analysis_app.py](tennis_analysis_app.py)의 상단 설정을 수정하세요:

```python
MAX_FILE_SIZE_MB = 100  # 최대 파일 크기 (MB)
MAX_VIDEO_DURATION_MINUTES = 1  # 최대 영상 길이 (분) - API 비용 절감
```

## ⚠️ 주의사항

- 동영상 파일 크기가 클 경우 업로드 및 분석에 시간이 걸릴 수 있습니다
- 유튜브 동영상 다운로드에는 추가 시간이 소요됩니다
- **Gemini API 비용이 발생하므로 제한을 설정하는 것을 권장합니다**
- Gemini API의 일일 사용량 제한을 확인하세요
- 안정적인 인터넷 연결이 필요합니다
- 유튜브 URL은 공개된 동영상만 지원됩니다 (비공개/삭제된 영상 불가)

## 📝 라이선스

MIT License
