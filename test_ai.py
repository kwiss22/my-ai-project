import requests
import json
from dotenv import load_dotenv
import os

load_dotenv()

def test_huggingface_api():
    token = os.getenv('HUGGINGFACE_TOKEN')
    if not token:
        print("토큰이 설정되지 않았습니다. .env 파일을 확인하세요.")
        return False
    
    print(f"토큰 확인됨: {token[:10]}...")
    
    API_URL = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "inputs": "안녕하세요",
        "parameters": {"max_length": 50}
    }
    
    try:
        print("API 테스트 중...")
        response = requests.post(API_URL, headers=headers, json=payload, timeout=15)
        print(f"상태 코드: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("응답 성공!")
            print(f"결과: {result}")
            return True
        else:
            print(f"오류: {response.text}")
            return False
            
    except Exception as e:
        print(f"연결 오류: {e}")
        return False

if __name__ == "__main__":
    test_huggingface_api()