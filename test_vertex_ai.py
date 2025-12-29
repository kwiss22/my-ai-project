import vertexai
from vertexai.generative_models import GenerativeModel
import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv('PROJECT_ID')
LOCATION = os.getenv('LOCATION', 'us-central1')

print(f"=== Vertex AI 테스트 ===")
print(f"프로젝트 ID: {PROJECT_ID}")
print(f"지역: {LOCATION}\n")

try:
    # Vertex AI 초기화
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    print("[OK] Vertex AI 초기화 성공!\n")

    # 모델 생성
    model = GenerativeModel("gemini-2.0-flash-exp")
    print("[OK] 모델 생성 성공!\n")

    # 간단한 테스트
    print("=== 간단한 응답 테스트 ===")
    response = model.generate_content("Say hello in one sentence")
    print(f"응답: {response.text}\n")

    # 대화 세션 테스트
    print("=== 대화 세션 테스트 ===")
    system_prompt = "You are a teacher. Once student says their grade, NEVER ask again."

    model2 = GenerativeModel(
        "gemini-2.0-flash-exp",
        system_instruction=[system_prompt],
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
        print("[ERROR] 문제: 학년을 다시 물어봤습니다!")
    else:
        print("[OK] 성공: 학년을 다시 물어보지 않았습니다!")

except Exception as e:
    print(f"[ERROR] 오류 발생: {str(e)}")
    import traceback
    traceback.print_exc()
