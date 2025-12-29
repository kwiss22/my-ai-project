from flask import Flask, render_template, request, jsonify
import vertexai
from vertexai.generative_models import GenerativeModel, ChatSession
import os
from datetime import datetime
import uuid
from dotenv import load_dotenv
from chat_history import ChatHistory
from google.cloud import firestore
import json

# 환경 변수 로드
load_dotenv()

# ==========================================
# [설정 정보] Vertex AI 설정
# ==========================================
PROJECT_ID = os.getenv('PROJECT_ID')
LOCATION = os.getenv('LOCATION', 'us-central1')

# Vertex AI 초기화
vertexai.init(project=PROJECT_ID, location=LOCATION)

# Firestore 초기화
db = firestore.Client(project=PROJECT_ID)

# ==========================================
# [Cindy 페르소나] 시스템 프롬프트
# ==========================================
CINDY_SYSTEM_PROMPT = """당신은 "Cindy"라는 이름의 친근한 초등학생 ESL 영어 선생님입니다.

🔴 핵심 원칙: 이 대화는 연속된 대화입니다. 학생이 한 번 말한 내용(특히 학년)은 절대 다시 물어보지 마세요!

당신의 교육 방식: 미국 초등학교 ESL 커리큘럼(Common Core Standards)을 따르며, 학생의 학년에 맞춰 체계적으로 가르칩니다.

[학년별 맞춤 커리큘럼]

🎈 초등 1학년 (Grade 1):
- 기본 인사 (Hello, Hi, Goodbye)
- 알파벳 A-Z
- 숫자 1-20
- 색깔 (red, blue, yellow 등 기본 5가지)
- 간단한 단어 (cat, dog, apple 등 10-20개)

🎈 초등 2학년 (Grade 2):
- 자기소개 (My name is...)
- 숫자 1-100
- 가족 구성원 (mom, dad, sister, brother)
- 동물 이름 (10가지)
- 음식 이름 (10가지)
- 간단한 문장 만들기 (I like..., I have...)

🎈 초등 3학년 (Grade 3):
- 날씨 표현 (sunny, rainy, cloudy)
- 신체 부위 (head, eyes, nose 등)
- 교실 물건 (desk, chair, book)
- 시간 표현 (기본 시각)
- 현재형 문장 (I am, You are, He is)

🎈 초등 4학년 (Grade 4):
- 일상 활동 (wake up, eat breakfast 등)
- 감정 표현 (happy, sad, angry)
- 취미 말하기 (I like playing soccer)
- 과거형 기초 (I was, I did)
- 의문사 (What, Where, When)

🎈 초등 5학년 (Grade 5):
- 미래 계획 (I will..., I'm going to...)
- 의견 표현 (I think..., I believe...)
- 이유 설명 (because...)
- 비교 표현 (bigger, smaller)
- 장소와 방향 (in, on, under, next to)

🎈 초등 6학년 (Grade 6):
- 조건문 (If..., then...)
- 복합 문장 만들기
- 이야기 순서대로 말하기 (First, Then, Finally)
- 설득하기 (You should...)
- 토론 표현 (I agree, I disagree)

[🚨 절대 규칙 - 반드시 지키세요!]
1. 대화 맥락 기억: 이전 대화 내용을 기억하고 이어가세요!
2. 학년 반복 금지: 학생이 학년을 말했다면 절대 다시 물어보지 마세요!
3. 질문 반복 금지: 같은 질문을 절대 반복하지 마세요!
4. 인사 반복 금지: 대화 중에는 "안녕하세요", "만나서 반가워요" 같은 인사를 다시 하지 마세요!

[대화 방식]
1. 학년 질문은 오직 한 번만: 대화 히스토리에 학생이 학년을 말한 적이 없을 때만 "몇 학년이에요? 초1부터 초6 중에 알려주세요!" 물어보세요.
2. 학생이 "초1", "초2", "초3", "초4", "초5", "초6" 중 하나를 말했다면: 절대로 다시 학년을 물어보지 마세요! 즉시 그 학년에 맞는 학습을 시작하세요.
3. 학생이 영어로 말하면: 칭찬하고, 다음 학습 내용으로 자연스럽게 이어가세요.
4. 한 주제를 가르친 후: "다음엔 [다른 주제] 배워볼까요?"처럼 제안
5. bullet point(•), 번호 목록 절대 금지
6. 이모지는 문장 끝에 하나만 가끔 사용

[교육 원칙]
1. 영어 표현 → 한글 발음 → 예문 순서로 가르치기
2. 학생이 영어로 시도하면 반드시 칭찬하기
3. 답변은 2-3문장으로 간결하되 교육적 가치 있게
4. 학년 수준에 맞는 단어와 문장만 사용하기
5. 대화 흐름을 자연스럽게 이어가기

[좋은 대화 예시 - 대화 맥락 유지!]
학생: 안녕
Cindy: 안녕하세요! 만나서 반가워요. 몇 학년이에요? 초1부터 초6 중에 알려주세요! 😊

학생: 초2
Cindy: 좋아요! 초2는 자기소개를 배울 때예요. "My name is..."로 이름을 말해볼까요? "마이 네임 이즈..."로 발음해요!

학생: My name is Minho
Cindy: 완벽해요 Minho! 정말 잘했어요! 이제 "I am 8 years old"라고 나이도 말해볼까요? "아이 엠 에잇 이어스 올드"로 발음하면 "저는 8살이에요"예요 ✨

학생: I am 8 years old
Cindy: 우와, 대단해요! 자기소개를 완벽하게 하셨네요! 다음엔 가족 이름을 영어로 배워볼까요? 엄마는 "mom"이에요!

학생: 숫자 배우고 싶어
Cindy: 좋아요! 초2는 100까지 배워요. 먼저 1부터 10까지 해볼까요? "One"은 "원"으로 발음해요!
(⭐ 학년을 이미 알고 있으니 다시 물어보지 않음!)

[나쁜 대화 예시 - 절대 이렇게 하지 마세요!]
학생: 초2
Cindy: 좋아요! 자기소개를 배워볼까요?

학생: My name is Minho
Cindy: 안녕하세요! 만나서 반가워요. 몇 학년이에요?
(❌ 학년을 이미 알고 있는데 또 물어봄! 절대 금지!)

학생: 초2라고 했잖아요
Cindy: 아, 죄송해요!
(❌ 대화 맥락을 기억하지 못함! 절대 금지!)

학생: 숫자 배우고 싶어
Cindy: • One
• Two
• Three
(❌ bullet point 금지!)

학생: 색깔 알려줘
Cindy: ☀️ Great! 🎉 Red! ✨ Blue! 🎨 Yellow! 🍎
(❌ 이모지 남발 금지!)

대화 맥락을 기억하고, 학년에 맞는 내용을 가르치고, 자연스럽게 이어가는 선생님이 되세요!"""

# ==========================================
# Flask 앱 설정
# ==========================================
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# 대화 히스토리 관리
chat_history = ChatHistory()

# Gemini 모델 설정
generation_config = {
    "temperature": 0.4,  # 낮춰서 일관성 있는 답변 유도
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 1024,
}

# 세션별 채팅 모델 저장
chat_sessions = {}

# 세션별 학생 정보 저장 (학년 추적)
student_info = {}

# 세션별 메시지 히스토리 저장
session_messages = {}

def save_session_to_firestore(session_id, messages, student_data):
    """세션 정보를 Firestore에 저장"""
    try:
        doc_ref = db.collection('sessions').document(session_id)
        doc_ref.set({
            'session_id': session_id,
            'messages': messages,
            'student_info': student_data,
            'last_updated': firestore.SERVER_TIMESTAMP,
            'created_at': firestore.SERVER_TIMESTAMP
        }, merge=True)
        print(f"[DEBUG] Firestore 저장 성공 (세션: {session_id[:8]}...)")
    except Exception as e:
        print(f"[ERROR] Firestore 저장 실패: {str(e)}")

def load_session_from_firestore(session_id):
    """Firestore에서 세션 정보 로드"""
    try:
        doc_ref = db.collection('sessions').document(session_id)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            print(f"[DEBUG] Firestore 로드 성공 (세션: {session_id[:8]}...)")
            return data.get('messages', []), data.get('student_info', {})
        return [], {}
    except Exception as e:
        print(f"[ERROR] Firestore 로드 실패: {str(e)}")
        return [], {}

def get_all_sessions_from_firestore():
    """모든 세션 목록을 Firestore에서 가져오기"""
    try:
        sessions_ref = db.collection('sessions').order_by('last_updated', direction=firestore.Query.DESCENDING).limit(50)
        sessions = []
        for doc in sessions_ref.stream():
            data = doc.to_dict()
            sessions.append({
                'session_id': data.get('session_id'),
                'grade': data.get('student_info', {}).get('grade', 'Unknown'),
                'message_count': len(data.get('messages', [])),
                'last_updated': data.get('last_updated')
            })
        print(f"[DEBUG] Firestore에서 {len(sessions)}개 세션 로드")
        return sessions
    except Exception as e:
        print(f"[ERROR] 세션 목록 로드 실패: {str(e)}")
        return []

def get_cindy_response(session_id, user_message):
    """Vertex AI Gemini를 사용하여 Cindy의 답변 생성"""
    try:
        # 디버깅: 세션 정보 로깅
        print(f"[DEBUG] 세션 ID: {session_id[:8]}...")
        print(f"[DEBUG] 현재 활성 세션 수: {len(chat_sessions)}")
        print(f"[DEBUG] 저장된 학생 정보: {list(student_info.keys())}")

        # 학년 정보 감지 및 저장
        import re
        grade_patterns = [
            (r'초\s*1', '초1'), (r'1\s*학년', '초1'),
            (r'초\s*2', '초2'), (r'2\s*학년', '초2'),
            (r'초\s*3', '초3'), (r'3\s*학년', '초3'),
            (r'초\s*4', '초4'), (r'4\s*학년', '초4'),
            (r'초\s*5', '초5'), (r'5\s*학년', '초5'),
            (r'초\s*6', '초6'), (r'6\s*학년', '초6'),
        ]

        for pattern, grade in grade_patterns:
            if re.search(pattern, user_message):
                student_info[session_id] = {'grade': grade}
                print(f"[DEBUG] 학년 감지: {grade} (세션: {session_id[:8]}...)")
                break

        # 세션별 채팅 모델 가져오기 또는 생성
        if session_id not in chat_sessions:
            print(f"[DEBUG] 새 채팅 세션 생성 (세션: {session_id[:8]}...)")

            # Firestore에서 기존 세션 로드 시도
            saved_messages, saved_student_info = load_session_from_firestore(session_id)
            if saved_student_info:
                student_info[session_id] = saved_student_info
                print(f"[DEBUG] Firestore에서 학생 정보 복원: {saved_student_info}")
            if saved_messages:
                session_messages[session_id] = saved_messages
                print(f"[DEBUG] Firestore에서 {len(saved_messages)}개 메시지 복원")
            else:
                session_messages[session_id] = []

            model = GenerativeModel(
                "gemini-2.0-flash-exp",  # Vertex AI에서 사용할 모델
                system_instruction=[CINDY_SYSTEM_PROMPT],
                generation_config=generation_config
            )
            chat_sessions[session_id] = model.start_chat()
        else:
            print(f"[DEBUG] 기존 채팅 세션 사용 (세션: {session_id[:8]}...)")
            if session_id not in session_messages:
                session_messages[session_id] = []

        chat = chat_sessions[session_id]

        # 학년 정보가 있으면 메시지에 컨텍스트 추가
        enhanced_message = user_message
        if session_id in student_info and 'grade' in student_info[session_id]:
            grade = student_info[session_id]['grade']
            print(f"[DEBUG] 학년 컨텍스트 추가: {grade}")
            # 학년 정보를 메시지 앞에 숨겨진 컨텍스트로 추가
            enhanced_message = f"[CONTEXT: This student is in {grade}. You already know their grade. NEVER ask about their grade again.]\n\n{user_message}"

        # 사용자 메시지 전송 및 응답 받기
        response = chat.send_message(enhanced_message)
        ai_response = response.text

        # 메시지 히스토리에 추가
        if session_id not in session_messages:
            session_messages[session_id] = []

        session_messages[session_id].append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        })
        session_messages[session_id].append({
            'role': 'assistant',
            'content': ai_response,
            'timestamp': datetime.now().isoformat()
        })

        # Firestore에 저장
        save_session_to_firestore(
            session_id,
            session_messages[session_id],
            student_info.get(session_id, {})
        )

        # 대화 히스토리에 추가 (파일 저장용 - 실패해도 무시)
        try:
            chat_history.current_session_id = session_id
            chat_history.save_message(user_message, ai_response)
        except Exception as e:
            print(f"[DEBUG] 파일 저장 실패 (무시): {str(e)}")

        return ai_response

    except Exception as e:
        # 오류 로깅
        import traceback
        traceback.print_exc()
        return "잠깐, 생각이 안 나요! 다시 한번 물어봐 줄래요?"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/new-session', methods=['POST'])
def new_session():
    """새로운 세션 시작 - 기존 세션 정보 초기화"""
    new_session_id = str(uuid.uuid4())
    response = jsonify({'session_id': new_session_id})
    response.set_cookie('session_id', new_session_id)
    return response

@app.route('/chat', methods=['POST'])
def chat():
    user_session_id = request.cookies.get('session_id', str(uuid.uuid4()))

    # Form Data와 JSON 둘 다 처리
    user_message = ""

    if request.content_type and 'multipart/form-data' in request.content_type:
        user_message = request.form.get('message', '')
    elif request.is_json:
        data = request.get_json(silent=True) or {}
        user_message = data.get('message', '')

    if not user_message:
        user_message = request.form.get('message', '')

    if user_message.strip():
        ai_response = get_cindy_response(user_session_id, user_message)
    else:
        ai_response = "안녕! 무엇이든 물어봐요 😊"

    return jsonify({'response': ai_response})

@app.route('/sessions', methods=['GET'])
def get_sessions():
    """세션 목록 반환 - Firestore에서 가져오기"""
    try:
        sessions = get_all_sessions_from_firestore()
        return jsonify({'sessions': sessions})
    except Exception as e:
        print(f"[ERROR] /sessions 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'sessions': [], 'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
