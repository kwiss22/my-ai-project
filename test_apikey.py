import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('GOOGLE_API_KEY')

print(f"API Key: {API_KEY}")
print("=" * 50)

try:
    genai.configure(api_key=API_KEY)
    print("[OK] API 키 설정 성공")

    model = genai.GenerativeModel("gemini-1.5-flash")
    print("[OK] 모델 생성 성공")

    response = model.generate_content("안녕하세요!")
    print("[OK] 응답 받기 성공")
    print(f"\n응답: {response.text}")

except Exception as e:
    print(f"\n[ERROR] 오류 발생!")
    print(f"오류 타입: {type(e).__name__}")
    print(f"오류 메시지: {e}")
