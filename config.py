import os
import streamlit as st
from dotenv import load_dotenv

# Load .env for local development
load_dotenv()

def _get_secret(key: str) -> str | None:
    """Read from Streamlit secrets first, then fall back to environment variables."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        # st.secrets may raise if no secrets.toml exists (e.g., in a fresh clone)
        pass
    return os.getenv(key)

GROQ_API_KEY = _get_secret("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError(
        "❌ GROQ_API_KEY is not set.\n"
        "   Locally: add it to your .env file.\n"
        "   On Streamlit Cloud: add it in the app's Secrets settings."
    )

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_FALLBACK_MODEL = "openai/gpt-oss-20b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"