"""Vertex AI Gemini 연결 테스트"""
import os
from dotenv import load_dotenv
import vertexai
from vertexai.generative_models import GenerativeModel

# 환경 변수 로드
load_dotenv()

PROJECT_ID = os.getenv('PROJECT_ID', 'cindylemclass')
LOCATION = os.getenv('LOCATION', 'us-central1')

print(f"PROJECT_ID: {PROJECT_ID}")
print(f"LOCATION: {LOCATION}")
print("=" * 50)

try:
    # Vertex AI 초기화
    print("Vertex AI 초기화 중...")
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    print("[OK] Vertex AI 초기화 성공")

    # Gemini 모델 생성
    print("\nGemini 모델 생성 중...")
    model = GenerativeModel("gemini-1.5-flash")
    print("[OK] Gemini 모델 생성 성공")

    # 테스트 메시지 전송
    print("\n테스트 메시지 전송 중...")
    response = model.generate_content("안녕하세요! 간단히 인사해주세요.")
    print("[OK] 응답 받기 성공")
    print(f"\n응답: {response.text}")

except Exception as e:
    print(f"\n[ERROR] 오류 발생!")
    print(f"오류 타입: {type(e).__name__}")
    print(f"오류 메시지: {e}")
    import traceback
    print("\n상세 오류:")
    traceback.print_exc()
