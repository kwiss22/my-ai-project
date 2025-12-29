import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('GOOGLE_API_KEY')
genai.configure(api_key=API_KEY)

print("=== gemini-2.0-flash-exp 모델 테스트 ===\n")

try:
    model = genai.GenerativeModel('gemini-2.0-flash-exp')
    response = model.generate_content("Say hello in one sentence")
    print(f"✅ 성공! 응답: {response.text}\n")

    # Chat 테스트
    print("=== Chat 세션 테스트 ===")
    system_prompt = """You are a teacher. Once student says their grade, NEVER ask again."""

    model2 = genai.GenerativeModel(
        model_name='gemini-2.0-flash-exp',
        system_instruction=system_prompt,
        generation_config={
            "temperature": 0.4,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 200,
        }
    )

    chat = model2.start_chat()

    r1 = chat.send_message("I am in grade 2")
    print(f"학생: I am in grade 2")
    print(f"선생님: {r1.text}\n")

    r2 = chat.send_message("What is 1+1?")
    print(f"학생: What is 1+1?")
    print(f"선생님: {r2.text}\n")

    # 학년을 다시 물어보는지 확인
    if "grade" in r2.text.lower() and "what" in r2.text.lower():
        print("❌ 문제: 학년을 다시 물어봤습니다!")
    else:
        print("✅ 성공: 학년을 다시 물어보지 않았습니다!")

except Exception as e:
    print(f"❌ 오류 발생: {str(e)}")
