import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "")
IG_USER_ID = os.getenv("IG_USER_ID", "")
DATE_FROM = os.getenv("DATE_FROM", "")
DATE_TO = os.getenv("DATE_TO", "")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "data"))

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
REQUEST_DELAY = 0.5
MAX_RETRIES = 3

WP_ENABLED = os.getenv("WP_ENABLED", "false").lower() == "true"
WP_URL = os.getenv("WP_URL", "").rstrip("/")
WP_USER = os.getenv("WP_USER", "")
WP_APP_PASS = os.getenv("WP_APP_PASS", "")
WP_POST_STATUS = os.getenv("WP_POST_STATUS", "draft")
WP_TEMPLATE_POST_ID = int(os.getenv("WP_TEMPLATE_POST_ID", "0"))
