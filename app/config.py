"""Settings from environment / .env (no extra dependency)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("LUMINA_DATA", ROOT / "data"))
SAMPLES_DIR = ROOT / "samples"
WEB_DIR = ROOT / "web"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
PIAPI_KEY = os.getenv("PIAPI_KEY", "")
# PiAPI accepts "url or base64" for the image; the exact base64 form isn't documented.
PIAPI_IMAGE_FORMAT = os.getenv("PIAPI_IMAGE_FORMAT", "datauri")  # datauri | raw

# "auto" = real provider when its key is set, mock otherwise.
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "auto")
MODEL3D_PROVIDER = os.getenv("MODEL3D_PROVIDER", "auto")
# Seconds each mock step waits, to rehearse the progress UI without paying for real calls.
MOCK_DELAY = float(os.getenv("MOCK_DELAY", "0") or 0)
