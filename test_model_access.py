import vertexai
from vertexai.generative_models import GenerativeModel
import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv('PROJECT_ID', 'cindylemclass')
LOCATION = os.getenv('LOCATION', 'us-central1')

print(f"Testing Vertex AI model access...")
print(f"Project: {PROJECT_ID}")
print(f"Location: {LOCATION}")
print("=" * 50)

try:
    # Initialize Vertex AI
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    print("[OK] Vertex AI initialized")

    # Try to create model
    model = GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config={
            "temperature": 0.9,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 1024,
        }
    )
    print("[OK] Model created")

    # Try to send a message
    chat = model.start_chat()
    print("[OK] Chat started")

    response = chat.send_message("Hello, say hi in Korean!")
    print("[OK] Response received")
    print(f"\nResponse: {response.text}")

except Exception as e:
    import traceback
    print(f"\n[ERROR] Failed!")
    print(f"Error type: {type(e).__name__}")
    print(f"Error message: {e}")
    traceback.print_exc()
