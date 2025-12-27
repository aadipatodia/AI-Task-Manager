import google.generativeai as genai

genai.configure(api_key="AIzaSyDu-s-BG6WJIOkFRUky7jlvAg1pirJAfvU")

print("Available models:")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(f"Name: {m.name}")