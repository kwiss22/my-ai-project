import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('GOOGLE_API_KEY')
genai.configure(api_key=API_KEY)

print("Available models:")
print("=" * 50)

for model in genai.list_models():
    if 'generateContent' in model.supported_generation_methods:
        print(f"Model: {model.name}")
        print(f"  Display name: {model.display_name}")
        print(f"  Description: {model.description[:100]}...")
        print()
