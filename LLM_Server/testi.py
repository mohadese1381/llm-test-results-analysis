""" import requests

API_URL = "https://api-inference.huggingface.co/models/tiiuae/falcon-rw-1b"
API_TOKEN = "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"  

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

data = {
    "inputs": "Translate English to French: How are you?",
    "parameters": {"max_new_tokens": 50}
}

response = requests.post(API_URL, headers=headers, json=data)

print("Status Code:", response.status_code)
print("Response:")
print(response.json()) """
import requests

API_KEY = "490acbd83989f44751fa2f6ec07bf7b9f247e5f87fa5309983be9e6622aa43eb" 

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "messages": [
        {"role": "user", "content": "Explain what unit testing is."}
    ],
    "temperature": 0.7,
    "max_tokens": 300
}

response = requests.post(API_URL, headers=headers, json=data)

print("Status Code:", response.status_code)
try:
    print(response.json()["choices"][0]["message"]["content"])
except Exception as e:
    print("❌ خطا در تحلیل پاسخ:", e)
    print("پاسخ خام:", response.text)

