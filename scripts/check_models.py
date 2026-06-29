from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

print("Modelos disponibles en tu cuenta:")
for m in client.models.list():
    print(f"- {m.name}")