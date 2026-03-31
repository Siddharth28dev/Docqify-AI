import google.generativeai as genai
import os

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if not API_KEY:
    raise SystemExit("Set GEMINI_API_KEY before running this diagnostic.")

genai.configure(api_key=API_KEY)

try:
    print("Checking available models...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Model: {m.name}")
except Exception as e:
    print(f"Error: {e}")
