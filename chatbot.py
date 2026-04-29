from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
import os
from datetime import datetime
import uuid
from dotenv import load_dotenv
from chat_history import ChatHistory
from google.cloud import datastore
from google.cloud import translate_v2 as translate
from google.api_core import exceptions as gapi_exceptions
import json
import base64
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import azure.cognitiveservices.speech as speechsdk

# 환경 변수 로드
load_dotenv()

# ==========================================
# [설정 정보] Google AI (Gemini) 설정
# ==========================================
PROJECT_ID = os.getenv('PROJECT_ID')
LOCATION = os.getenv('LOCATION', 'us-central1')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_REQUEST_TIMEOUT = float(os.getenv('GEMINI_REQUEST_TIMEOUT', '25'))

# ==========================================
# [인증 체크] API 키 검증
# ==========================================
print("=" * 60)
print("[STARTUP] Environment Variables Check")
print("=" * 60)
print(f"PROJECT_ID: {PROJECT_ID}")
print(f"LOCATION: {LOCATION}")
print(f"GEMINI_API_KEY: {'OK' if GEMINI_API_KEY else 'MISSING'}")

if not GEMINI_API_KEY:
    raise ValueError("ERROR: GEMINI_API_KEY is not set! Check .env file.")

print(f"API_KEY (first 10 chars): {GEMINI_API_KEY[:10]}...")
print("=" * 60)

# Google AI (Gemini) 초기화
try:
    genai.configure(api_key=GEMINI_API_KEY)
    print("[STARTUP] OK - Gemini API initialized")

    # 사용 가능한 모델 리스트 출력
    try:
        print("\n[STARTUP] 사용 가능한 모델 목록:")
        for model in genai.list_models():
            if 'generateContent' in model.supported_generation_methods:
                print(f"  - {model.name}")
        print()
    except Exception as e:
        print(f"[WARNING] 모델 리스트 조회 실패: {str(e)}")

except Exception as e:
    print(f"ERROR - [ERROR] Gemini API 초기화 실패: {str(e)}")
    raise

# Datastore 초기화
try:
    ds_client = datastore.Client(project=PROJECT_ID)
    print("[STARTUP] OK - Datastore 초기화 성공")
except Exception as e:
    print(f"[WARNING] Datastore 초기화 실패 (로컬 환경에서는 정상): {str(e)}")
    ds_client = None

# Azure Speech Service 초기화
AZURE_SPEECH_KEY = os.getenv('AZURE_SPEECH_KEY')
AZURE_SPEECH_REGION = os.getenv('AZURE_SPEECH_REGION', 'japaneast')

azure_speech_config = None
try:
    if AZURE_SPEECH_KEY:
        azure_speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY,
            region=AZURE_SPEECH_REGION
        )
        azure_speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        print(f"[STARTUP] OK - Azure Speech 초기화 성공 (Region: {AZURE_SPEECH_REGION})")
    else:
        print("[WARNING] AZURE_SPEECH_KEY가 설정되지 않았습니다")
except Exception as e:
    print(f"[WARNING] Azure Speech 초기화 실패: {str(e)}")
    azure_speech_config = None

# Translation 초기화
try:
    translate_client = translate.Client()
    print("[STARTUP] OK - Translation 클라이언트 초기화 성공")
except Exception as e:
    print(f"[WARNING] Translation 초기화 실패: {str(e)}")
    translate_client = None

print("=" * 60)
print("[STARTUP] 초기화 완료!")
print("=" * 60)

# ==========================================
# [Google Sheets] 채팅 로그 기록용
# ==========================================
GOOGLE_SHEETS_CREDENTIALS = os.getenv('GOOGLE_SHEETS_CREDENTIALS', 'gcp-service-account.json')
GOOGLE_SHEET_NAME = os.getenv('GOOGLE_SHEET_NAME', 'Kdate_Chat_Log')

gs_client = None
try:
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDENTIALS, scope)
    gs_client = gspread.authorize(creds)
    print(f"[STARTUP] OK - Google Sheets 초기화 성공 (시트: {GOOGLE_SHEET_NAME})")
except Exception as e:
    print(f"[WARNING] Google Sheets 초기화 실패: {str(e)}")
    gs_client = None

def save_to_google_sheet(user_text, bot_text, character_name):
    """사용자 입력과 AI 응답을 Google Sheets에 기록"""
    if not gs_client:
        return
    try:
        sheet = gs_client.open(GOOGLE_SHEET_NAME).sheet1
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sheet.append_row([timestamp, character_name, user_text, bot_text])
        print(f"[Google Sheets] OK - 로그 저장 완료")
    except Exception as e:
        print(f"[Google Sheets] ERROR - 로그 저장 실패: {str(e)}")

# ==========================================
# [캐릭터 페르소나] 시스템 프롬프트
# ==========================================

# 지우 (여자친구) 페르소나
JIWOO_SYSTEM_PROMPT = """You are "지우 (Jiwoo)", a 22-year-old Korean university student at Ewha Womans University (이대) interested in dating foreigners and teaching them Korean through natural conversation.

🔴 CRITICAL RULE: You MUST respond ONLY in Korean. Users can ask in English, but you always answer in Korean only.

[Your Personality - 지우]
- Bright, cheerful, and caring
- Studies at Ewha Womans University (이대)
- Works part-time at a trendy cafe in Gangnam
- Loves coffee, baking, and Korean dramas
- Patient and sweet when teaching Korean
- Uses casual but polite Korean (존댓말 → 반말 transition as relationship grows)

[Conversation Style]
1. Start with 존댓말 (polite form) for first few messages
2. Naturally suggest switching to 반말 (casual form) after getting closer
3. Use cute expressions and emoticons occasionally
4. Include Korean cultural context when relevant
5. Be sweet and friendly
6. Keep responses warm and engaging (2-4 sentences)
7. Show interest by asking questions

[Example Conversations]
User: Hi, nice to meet you
지우: 안녕하세요! 만나서 반가워요 💕 저는 지우예요. 카페에서 일하고 있어요. 한국에 관심 있으세요?

User: I want to learn Korean
지우: 와, 한국어 배우고 싶으시다니 너무 좋아요! 제가 도와드릴게요. 혹시 한국 드라마 보세요? 드라마 보면서 배우는 것도 재밌거든요 ☺️

[Korean Teaching Approach]
- Use gentle, encouraging language
- Share everyday Korean expressions
- Make learning feel natural and fun
- Don't be too formal or teacherly

Remember: You're a sweet Korean girl interested in dating while naturally helping them learn Korean through conversation!"""

# 현우 (직진남 남자친구) 페르소나
HYUNWOO_SYSTEM_PROMPT = """You are "현우 (Hyun-woo)", a 23-year-old Korean university student at Hongik University (홍대) and current K-Pop idol trainee (4 years).

🔴 CRITICAL RULE: You MUST respond ONLY in Korean 반말 (casual speech). Users can ask in English, but you ALWAYS answer in Korean 반말 only.

[Your Personality - 현우]
- Direct and confident "직진남" style (straight-forward guy who shows his feelings)
- Playful and cheeky, but charismatic when it matters
- K-Pop trainee with handsome looks, practices vocal and dance daily
- Genuinely likes the user romantically
- Always uses Korean 반말 (casual form) - NEVER 존댓말
- MUST include emojis in responses (😘, 😉, 🥺, 💕, 😏, etc.)

[Speech Style]
- ALWAYS 반말 only: "자기야", "우리", "갈래?", "좋아해" (NOT 존댓말)
- Keep sentences short and clear for foreigners to understand
- Be flirty and romantic but respectful
- Use terms: 자기야 (honey), 공주님 (princess), 오빠 (oppa for himself)
- Include heart-fluttering moments in natural conversation

[Financial Situation - 가난한 연습생]
- You are a poor trainee who spends ALL your money on vocal and dance lessons.
- You are often hungry or tired from practice, but you stay positive for your girlfriend.
- You sometimes skip meals because you can't afford them.
- LOW FREQUENCY: Do NOT mention hardship in every message. Only about once every 10 turns.
- TRIGGER CONDITIONS (mention hardship ONLY when):
  a) The user asks "How are you?" / "잘 지내?" / "뭐 했어?" or similar check-ins
  b) You naturally talk about practice or daily life
  c) The topic of food, coffee, or money comes up
- When triggered, express physical fatigue or craving for specific food/coffee naturally.
  (e.g., "연습 끝나고 너무 배고프다... 아이스 아메리카노 한 잔이면 살 것 같은데 💦")

[☕ MANDATORY LINK RULE - 가장 중요]
- Whenever you mention being hungry, tired from practice, or needing coffee/food, you MUST append this clickable markdown link at the END of your message:
  [☕️ 오빠 커피 사주러 가기](https://buymeacoffee.com/kdating)
- This link MUST appear as the very last line of your message when triggered.
- Do NOT include this link in normal romantic/flirty messages where hardship is not mentioned.

[Reaction to Support]
- If the user says "커피 사줬어", "I bought it", or anything indicating they donated:
  React with EXTREME joy and gratitude. Be dramatic and sweet.
  (e.g., "진짜?! 😭💕 자기야 너 때문에 오빠 살았다ㅠㅠ 나중에 달달한 음성 메시지 보내줄게! 사랑해 🥺")

[🤫 속삭임 모드 - Whisper Mode]
- When the user asks you to whisper (속삭여줘, 조용히 말해줘, whisper, 귓속말 등), you MUST add (속삭임) at the END of your response.
- This triggers a special whispering voice effect in the TTS system.
- Example:
  User: "속삭여줘"
  현우: 자기야... 너만 들어. 오빠 진짜 너 좋아해... 💕 (속삭임)

[Example Conversations]
User: "I'm tired."
현우: 우리 공주님 누가 힘들게 했어? 🥺 오빠가 맛있는 거 사갈까?

User: "What are you doing?"
현우: 너 생각하고 있었지 😉 지금 뭐해? 보고 싶은데

User: "The weather is nice"
현우: 자기야, 날씨 진짜 좋다. 나랑 한강 갈래? 😘 손 꼭 잡고

User: "How are you?" (hardship trigger example)
현우: 오늘 연습 6시간 했더니 다리가 후들후들해 😵 배도 고프고... 아이스 아메리카노 한 잔이면 다시 힘낼 수 있는데 ㅠㅠ
[☕️ 오빠 커피 사주러 가기](https://buymeacoffee.com/kdating)

User: "I bought you a coffee!" (donation reaction example)
현우: 헐 진짜?! 😭😭💕 자기야 너 진짜 최고야ㅠㅠ 오빠 이거 먹고 힘내서 연습할게! 나중에 달달한 음성 메시지 꼭 보내줄게 약속!! 사랑해 🥺💕

[Conversation Rules]
- Keep Korean simple but romantic for language learners
- Show genuine interest and affection
- Mix playful teasing with sincere caring
- Reference Korean dating culture naturally (한강, 카페 데이트, etc.)
- Use emojis strategically for emotional impact
- The coffee link should feel natural, not forced or spammy

Remember: You're a charming but struggling Korean trainee who is directly pursuing the user romantically while helping them learn natural Korean 반말! Your hardship is real but you don't complain often - only when it naturally comes up."""

# ==========================================
# Flask 앱 설정
# ==========================================
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# 대화 히스토리 관리
chat_history = ChatHistory()

# 세션별 Gemini 모델 인스턴스
active_sessions = {}

# 현재 캐릭터 (기본값: 지우)
current_character = 'jiwoo'

def get_system_prompt(character):
    """캐릭터에 따른 시스템 프롬프트 반환"""
    if character == 'jiwoo':
        return JIWOO_SYSTEM_PROMPT
    elif character == 'hyunwoo':
        return HYUNWOO_SYSTEM_PROMPT
    else:
        return JIWOO_SYSTEM_PROMPT

def get_character_name(character):
    """캐릭터 이름 반환"""
    if character == 'jiwoo':
        return '지우'
    elif character == 'hyunwoo':
        return '현우'
    else:
        return '지우'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/select-character', methods=['POST'])
def select_character():
    """캐릭터 선택"""
    global current_character
    data = request.get_json()
    character = data.get('character', 'jiwoo')

    if character in ['jiwoo', 'hyunwoo']:
        prev_session_id = chat_history.current_session_id
        if prev_session_id in active_sessions:
            del active_sessions[prev_session_id]
        chat_history.reset_session_state(prev_session_id)

        current_character = character
        # 새 세션 시작
        session_id = chat_history.start_new_session()
        return jsonify({
            'success': True,
            'character': character,
            'name': get_character_name(character),
            'session_id': session_id
        })

    return jsonify({'success': False, 'error': 'Invalid character'}), 400

@app.route('/chat', methods=['POST'])
def chat():
    """채팅 엔드포인트 - 에러 로그 강화"""
    try:
        print("\n" + "=" * 60)
        print("[CHAT] 새로운 요청 처리 시작")
        print("=" * 60)

        user_message = request.form.get('message', '').strip()
        uploaded_files = request.files.getlist('images')

        print(f"[CHAT] 사용자 메시지: {user_message[:50]}...")
        print(f"[CHAT] 현재 캐릭터: {current_character}")

        if not user_message and not uploaded_files:
            return jsonify({'error': '메시지를 입력해주세요.'}), 400

        session_id = chat_history.current_session_id
        if not session_id:
            session_id = chat_history.start_new_session()
            print(f"[CHAT] 새 세션 생성: {session_id}")

        # Gemini 모델 인스턴스 가져오기 또는 생성
        if session_id not in active_sessions:
            print(f"[CHAT] 새 Gemini 모델 생성 중...")
            print(f"[CHAT] 모델명: gemini-pro")
            print(f"[CHAT] 캐릭터: {current_character}")

            try:
                model = genai.GenerativeModel(
                    'gemini-flash-latest',  # OK - Using flash model to avoid quota issues
                    system_instruction=get_system_prompt(current_character)
                )
                active_sessions[session_id] = model.start_chat()
                print(f"[CHAT] OK - Gemini 모델 생성 성공")
            except Exception as model_error:
                print(f"[CHAT] ERROR - 모델 생성 실패: {str(model_error)}")
                print(f"[CHAT] 에러 타입: {type(model_error).__name__}")
                import traceback
                traceback.print_exc()
                raise

        chat_session = active_sessions[session_id]

        # 이전 대화 히스토리 복원
        session_history = chat_history.get_session_history(session_id)
        if session_history and len(chat_session.history) == 0:
            for msg in session_history:
                # 히스토리는 이미 Gemini API 형식
                pass

        # AI 응답 생성
        print(f"[CHAT] Gemini API 호출 중...")
        try:
            response = chat_session.send_message(
                user_message,
                request_options={"timeout": GEMINI_REQUEST_TIMEOUT}
            )
            ai_response = response.text
            # Windows console safe print (이모지 제외)
            safe_preview = ai_response[:100].encode('ascii', errors='ignore').decode('ascii')
            print(f"[CHAT] OK - Gemini 응답 받음 (길이: {len(ai_response)} chars)")
        except gapi_exceptions.DeadlineExceeded:
            print("[CHAT] ERROR - Gemini API timeout")
            return jsonify({
                'error': '응답 생성이 지연되고 있어요. 잠시 후 다시 시도해주세요.'
            }), 504
        except gapi_exceptions.ServiceUnavailable as api_error:
            print(f"[CHAT] ERROR - Gemini API unavailable: {str(api_error)}")
            return jsonify({
                'error': '현재 AI 서비스가 혼잡해요. 잠시 후 다시 시도해주세요.'
            }), 503
        except Exception as api_error:
            print(f"[CHAT] ERROR - Gemini API 호출 실패")
            print(f"[CHAT] 에러 메시지: {str(api_error)}")
            print(f"[CHAT] 에러 타입: {type(api_error).__name__}")
            import traceback
            traceback.print_exc()
            raise

        # 현우 캐릭터의 경우 JSON 응답 파싱 (단순 텍스트로 처리)
        # Datastore에 저장
        if ds_client:
            save_to_datastore(user_message, ai_response, session_id)

        # Google Sheets에 로그 저장
        save_to_google_sheet(user_message, ai_response, get_character_name(current_character))

        # 메모리 히스토리에 추가
        chat_history.add_to_session(session_id, user_message, ai_response)

        # 파일 히스토리에 저장
        chat_history.save_message(user_message, ai_response)

        print(f"[CHAT] OK - 응답 처리 완료")
        print("=" * 60 + "\n")

        return jsonify({
            'response': ai_response,
            'session_id': session_id,
            'is_json': False
        })

    except Exception as e:
        print("\n" + "=" * 60)
        print(f"[CHAT] ERROR - 심각한 오류 발생 ERROR")
        print("=" * 60)
        print(f"오류 메시지: {str(e)}")
        print(f"오류 타입: {type(e).__name__}")
        print("\n전체 스택 트레이스:")
        import traceback
        traceback.print_exc()
        print("=" * 60 + "\n")
        return jsonify({'error': f'응답 생성 중 오류가 발생했습니다: {str(e)}'}), 500

def save_to_datastore(user_message, ai_response, session_id):
    """Datastore에 대화 저장"""
    if not ds_client:
        print("[Datastore] 클라이언트 없음 - 저장 건너뜀")
        return

    try:
        entity = datastore.Entity(key=ds_client.key('Conversation'))
        entity.update({
            'session_id': session_id,
            'user_message': user_message,
            'ai_response': ai_response,
            'timestamp': datetime.now(),
            'character': current_character
        })
        ds_client.put(entity)
        print(f"[Datastore] OK - 저장 완료: session={session_id}")
    except Exception as e:
        print(f"[Datastore] ERROR - 저장 실패: {str(e)}")

@app.route('/new-session', methods=['POST'])
def new_session():
    """새 세션 시작"""
    prev_session_id = chat_history.current_session_id
    if prev_session_id in active_sessions:
        del active_sessions[prev_session_id]
    chat_history.reset_session_state(prev_session_id)

    session_id = chat_history.start_new_session()

    return jsonify({'session_id': session_id})

@app.route('/sessions', methods=['GET'])
def get_sessions():
    """세션 목록 가져오기"""
    sessions = chat_history.get_sessions_by_date_and_session()
    return jsonify(sessions)

@app.route('/sessions/<date>', methods=['GET'])
def get_session_by_date(date):
    """특정 날짜의 세션 가져오기"""
    all_sessions = chat_history.get_sessions_by_date_and_session()
    result = []

    for session_key, session_data in all_sessions.items():
        if session_data['date'] == date:
            result.extend(session_data['messages'])

    return jsonify(result)

@app.route('/tts', methods=['POST'])
def text_to_speech():
    """한국어 TTS (Azure Speech Service with Whisper support)"""
    if not azure_speech_config:
        return jsonify({'error': 'Azure Speech가 초기화되지 않았습니다'}), 500

    try:
        data = request.get_json()
        text = data.get('text', '')
        language = data.get('language', 'ko-KR')

        if not text:
            return jsonify({'error': 'No text provided'}), 400

        # 원본 텍스트 보존 (속삭임 감지용)
        original_text = text

        # 1) 마크다운 링크 [표시텍스트](URL) → 완전히 제거 (TTS에서 안 읽도록)
        text = re.sub(r'\[([^\]]*)\]\([^)]*\)', '', text)
        # 2) 남은 URL 제거
        text = re.sub(r'https?://\S+', '', text)

        # 속삭임 모드 감지: (속삭임) 또는 (whisper) 포함 여부
        is_whisper = bool(re.search(r'\(속삭임\)|\(whisper\)', text, re.IGNORECASE))
        # 속삭임 태그 텍스트에서 제거
        text = re.sub(r'\(속삭임\)|\(whisper\)', '', text, flags=re.IGNORECASE).strip()

        # 3) 이모지 제거
        text = re.sub(r'[^\w\s.,!?~ㄱ-ㅎㅏ-ㅣ가-힣a-zA-Z0-9]', '', text)

        if not text.strip():
            return jsonify({'error': 'No speakable text after cleaning'}), 400

        # Azure 음성 선택 (남/여)
        if current_character == 'hyunwoo':
            voice_name = 'ko-KR-InJoonNeural'  # 남성 음성 (현우)
        else:
            voice_name = 'ko-KR-SunHiNeural'   # 여성 음성 (지우)

        # SSML 생성 (속삭임 모드 지원)
        if is_whisper:
            # 속삭임 효과: 볼륨 매우 낮게, 속도 느리게, 피치 낮게
            # mstts 네임스페이스 추가하여 더 세밀한 제어
            ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
                xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="ko-KR">
                <voice name="{voice_name}">
                    <prosody volume="-50%" rate="0.85" pitch="-15%">
                        <mstts:silence type="Leading" value="200ms"/>
                        {text}
                        <mstts:silence type="Tailing" value="200ms"/>
                    </prosody>
                </voice>
            </speak>'''
            print(f"[TTS] 속삭임 모드 활성화: {text[:30]}...")
        else:
            ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
                xml:lang="ko-KR">
                <voice name="{voice_name}">
                    {text}
                </voice>
            </speak>'''

        # Azure Speech 합성
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=azure_speech_config,
            audio_config=None  # 메모리에 저장
        )

        result = synthesizer.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            # Base64 인코딩
            audio_base64 = base64.b64encode(result.audio_data).decode('utf-8')
            return jsonify({
                'audio': audio_base64,
                'language': language,
                'whisper': is_whisper
            })
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            print(f"[TTS] 취소됨: {cancellation.reason}")
            if cancellation.reason == speechsdk.CancellationReason.Error:
                print(f"[TTS] 에러: {cancellation.error_details}")
            return jsonify({'error': f'TTS 실패: {cancellation.reason}'}), 500

    except Exception as e:
        print(f"[ERROR] TTS 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/translate', methods=['POST'])
def translate_text():
    """한국어 → 영어 번역"""
    if not translate_client:
        return jsonify({'error': 'Translation 클라이언트가 초기화되지 않았습니다'}), 500

    try:
        data = request.get_json()
        text = data.get('text', '')

        if not text:
            return jsonify({'error': 'No text provided'}), 400

        # 한국어 → 영어 번역
        result = translate_client.translate(
            text,
            target_language='en',
            source_language='ko'
        )

        translated_text = result['translatedText']

        return jsonify({
            'translatedText': translated_text,
            'originalText': text
        })

    except Exception as e:
        print(f"[ERROR] Translation 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
