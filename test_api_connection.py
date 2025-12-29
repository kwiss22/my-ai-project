import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('GOOGLE_API_KEY')
print(f"API Key: {API_KEY[:20]}...")

genai.configure(api_key=API_KEY)

# 테스트 1: 간단한 대화
print("\n=== 테스트 1: 기본 대화 ===")
model = genai.GenerativeModel('gemini-2.5-flash')
response = model.generate_content("Hello, say hi back in one sentence.")
print(f"응답: {response.text}")

# 테스트 2: Chat 세션 - 학년 기억 테스트
print("\n=== 테스트 2: Chat 세션 - 학년 기억 테스트 ===")

system_prompt = """You are a teacher.
CRITICAL RULE: Once a student tells you their grade, NEVER ask about it again.
Remember the conversation context."""

model2 = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction=system_prompt
)

chat = model2.start_chat()

# 첫 번째 메시지
msg1 = "I am in grade 2"
response1 = chat.send_message(msg1)
print(f"\n학생: {msg1}")
print(f"선생님: {response1.text}")

# 두 번째 메시지
msg2 = "What subjects should I learn?"
response2 = chat.send_message(msg2)
print(f"\n학생: {msg2}")
print(f"선생님: {response2.text}")

# 세 번째 메시지 - 학년을 다시 물어보는지 확인
msg3 = "Tell me about math"
response3 = chat.send_message(msg3)
print(f"\n학생: {msg3}")
print(f"선생님: {response3.text}")

# 대화 히스토리 확인
print("\n=== 대화 히스토리 ===")
for i, message in enumerate(chat.history):
    print(f"{i+1}. {message.role}: {message.parts[0].text[:100]}...")
