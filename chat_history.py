# chat_history.py
import json
import os
from datetime import datetime
import uuid

class ChatHistory:
    def __init__(self, filename='chat_history.json'):
        self.filename = filename
        self.history = self.load_history()
        self.current_session_id = None
        # Gemini API용 세션별 대화 히스토리 (메모리 내)
        self.session_conversations = {}
    
    def load_history(self):
        """저장된 대화 기록 불러오기"""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def start_new_session(self):
        """새로운 세션 시작"""
        self.current_session_id = str(uuid.uuid4())[:8]  # 8자리 세션 ID
        return self.current_session_id
    
    def add_to_session(self, session_id, user_message, ai_response):
        """세션별 대화 히스토리에 추가 (Gemini API 형식)"""
        if session_id not in self.session_conversations:
            self.session_conversations[session_id] = []

        # Gemini API 형식으로 저장
        self.session_conversations[session_id].append({
            "role": "user",
            "parts": [user_message]
        })
        self.session_conversations[session_id].append({
            "role": "model",
            "parts": [ai_response]
        })

    def get_session_history(self, session_id):
        """특정 세션의 대화 히스토리 가져오기 (Gemini API 형식)"""
        return self.session_conversations.get(session_id, [])

    def save_message(self, user_message, ai_response):
        """새 대화 저장 (파일에 저장)"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 세션 ID가 없으면 새로 생성
        if not self.current_session_id:
            self.start_new_session()

        conversation = {
            "timestamp": timestamp,
            "user": user_message,
            "ai": ai_response,
            "session_id": self.current_session_id
        }

        self.history.append(conversation)
        self.save_to_file()
    
    def save_to_file(self):
        """파일에 저장"""
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"저장 오류: {e}")
    
    def get_recent_messages(self, count=10):
        """최근 대화 가져오기"""
        return self.history[-count:] if self.history else []
    
    def get_sessions_by_date_and_session(self):
        """날짜와 세션별로 그룹화"""
        sessions = {}
        for chat in self.history:
            date = chat['timestamp'].split(' ')[0]
            session_id = chat.get('session_id', 'default')
            session_key = f"{date}_{session_id}"
            
            if session_key not in sessions:
                sessions[session_key] = {
                    'date': date,
                    'session_id': session_id,
                    'session_name': f"{date} 세션 {session_id}",
                    'count': 0,
                    'first_message': '',
                    'last_time': '',
                    'messages': []
                }
            
            sessions[session_key]['count'] += 1
            sessions[session_key]['messages'].append(chat)
            if not sessions[session_key]['first_message']:
                sessions[session_key]['first_message'] = chat['user'][:30] + ('...' if len(chat['user']) > 30 else '')
            sessions[session_key]['last_time'] = chat['timestamp'].split(' ')[1]
        
        return sessions
    
    def clear_history(self):
        """대화 기록 초기화"""
        self.history = []
        self.current_session_id = None
        self.save_to_file()