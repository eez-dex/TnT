import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

def _get_secret(key: str) -> str | None:
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
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

# ---- Database ----
# Read from [connections.neon] in secrets.toml
try:
    DATABASE_URL = st.secrets["connections"]["neon"]["DATABASE_URL_POOLED"]
except Exception:
    DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "❌ DATABASE_URL is not set.\n"
        "   Locally: add [connections.neon] to .streamlit/secrets.toml\n"
        "   On Streamlit Cloud: add it in the app's Secrets settings."
    )