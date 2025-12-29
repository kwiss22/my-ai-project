import requests
import json

def test_chatbot(message):
    url = "http://127.0.0.1:5000/chat"
    data = {"message": message}
    
    try:
        response = requests.post(url, json=data)
        result = response.json()
        print(f"사용자: {message}")
        print(f"AI: {result['response']}")
        print("-" * 40)
    except Exception as e:
        print(f"에러: {e}")

if __name__ == "__main__":
    print("AI 챗봇 테스트를 시작합니다!\n")
    
    # 테스트 메시지들
    test_messages = [
        "안녕",
        "너의 이름은 뭐야?",
        "오늘 날씨 어때?",
        "현재 시간이 몇 시야?",
        "파이썬이 뭐야?"
    ]
    
    for message in test_messages:
        test_chatbot(message)