import google.generativeai as genai
import os

API_KEY = "AIzaSyAIBQQRLN6EBcdpxBjiMfqRw-KjkoY8Quw"
genai.configure(api_key=API_KEY)

def list_gemini_models():
    print(f"{'Model Name':<40} | {'Supported Methods'}")
    print("-" * 70)
    
    try:
        # 2. Call the list_models() method
        for m in genai.list_models():
            # Filter for models that support generating content
            if 'generateContent' in m.supported_generation_methods:
                methods = ", ".join(m.supported_generation_methods)
                print(f"{m.name:<40} | {methods}")
                
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    list_gemini_models()