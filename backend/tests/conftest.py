import os
import sys

os.environ.setdefault("STT_WARMUP", "0")  

API_PREFIX = os.getenv("API_PREFIX", "/api")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
