import vertexai
from vertexai.generative_models import GenerativeModel
import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv('PROJECT_ID', 'cindylemclass')
LOCATION = os.getenv('LOCATION', 'us-central1')

# Test different model names
models_to_test = [
    "gemini-pro",
    "gemini-1.0-pro",
    "gemini-1.5-pro",
    "gemini-flash",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash-002",
]

print(f"Testing different Gemini models...")
print(f"Project: {PROJECT_ID}")
print(f"Location: {LOCATION}")
print("=" * 50)

vertexai.init(project=PROJECT_ID, location=LOCATION)

for model_name in models_to_test:
    print(f"\nTesting: {model_name}")
    try:
        model = GenerativeModel(model_name=model_name)
        chat = model.start_chat()
        response = chat.send_message("Hi")
        print(f"  [SUCCESS] {model_name} works!")
        print(f"  Response: {response.text[:50]}...")
        break  # Found a working model
    except Exception as e:
        print(f"  [FAILED] {type(e).__name__}: {str(e)[:100]}")
