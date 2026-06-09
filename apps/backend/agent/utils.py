from dotenv import load_dotenv
import os

def load_config_gemini():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    config_list_gemini = [
        {
            "model": "gemini-1.5-pro",
            "api_key": api_key,
            "api_type": "google"
        }
    ]
    return config_list_gemini

def load_config_openai():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")

    config_list_gemini = [
        {
            "model": "gpt-4.1",
            "api_key": api_key,
            "api_type": "openai"
        }
    ]
    return config_list_gemini