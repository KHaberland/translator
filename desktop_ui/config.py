from os import getenv

from dotenv import load_dotenv


load_dotenv()

API_BASE_URL = getenv("DESKTOP_API_BASE_URL") or getenv(
    "API_BASE_URL",
    "http://localhost:8000",
)
POLL_INTERVAL = int(getenv("POLL_INTERVAL", "2"))
REQUEST_TIMEOUT = int(getenv("REQUEST_TIMEOUT", "30"))
