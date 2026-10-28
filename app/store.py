"""File-based storage: one folder per design + a settings file. Good enough for a prototype."""
import json
import os
import secrets
import shutil
import threading
import time
import uuid

from . import config
from .ring.postprocess import DENSITIES

_lock = threading.Lock()

DEFAULT_SETTINGS = {
    # business / branding (shown to clients)
    "business_name": "",
    "business_phone": "",
    "has_logo": False,
    # client sharing
    "public_url": "",  # e.g. https://studio.example.com - share links are built from it
    "share_message": "שלום {name}, זה העיצוב של הטבעת שלך מ{business}. אפשר לראות את הפרטים ולאשר כאן: {link}",
    "client_sees_specs": True,
    "client_sees_weight": False,
    # pricing / production
    "margin_percent": 0,
    "currency": "₪",
    "size_system": "circumference",
    # price per gram for every karat and colour, e.g. "14K white"; the jeweler fills in today's prices.
    # Older saves only have "14K" / "18K" keys; quote() falls back to those.
    "gold_price_per_gram": {"%s %s" % (k, m): 0 for k in ("14K", "18K") for m in ("yellow", "white", "rose")},
    "logo_background": "light",  # plate behind the logo: light | dark | none
    "labor_cost": 0,
    "wax_shrink": 1.0,
    "densities": DENSITIES,
}


def _write_json(path, obj):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def designs_dir():
    d = config.DATA_DIR / "designs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def design_dir(design_id):
    if not design_id.isalnum():
        raise KeyError(design_id)
    return designs_dir() / design_id


ORDER_STAGES = [
    ("design", "בעיצוב"),
    ("awaiting_approval", "ממתין לאישור הלקוח"),
    ("approved", "אושר על ידי הלקוח"),
    ("printing", "בהדפסת שעווה"),
    ("casting", "ביציקה"),
    ("finishing", "בשיבוץ וליטוש"),
    ("ready", "מוכן לאיסוף"),
    ("delivered", "נמסר"),
]
STAGE_IDS = [k for k, _ in ORDER_STAGES]


def _new_order():
    # published_price: what the client sees on the link, set only when the jeweler sends it
    return {"stage": "design", "stone_price": 0, "price_override": None, "deposit": 0, "notes": "",
            "published_price": None}


def create_design(selections, free_text, ring_size, client=None, engraving=""):
    design_id = uuid.uuid4().hex[:12]
    d = design_dir(design_id)
    d.mkdir(parents=True)
    design = {
        "id": design_id, "created_at": time.time(), "selections": selections, "free_text": free_text,
        "engraving": engraving, "ring_size": ring_size, "status": "queued", "step": "", "error": None,
        "progress": None, "images": [], "image": None, "stoneless_image": None, "spec": None, "glb_source": None,
        "client": {"name": "", "phone": "", **(client or {})},
        "order": _new_order(),
        "share_token": None, "approval": None,
    }
    save_design(design)
    return design


def load_design(design_id):
    path = design_dir(design_id) / "design.json"
    if not path.exists():
        raise KeyError(design_id)
    with open(path, encoding="utf-8") as f:
        design = json.load(f)
    # designs saved before orders/sharing existed
    design.setdefault("client", {"name": "", "phone": ""})
    design.setdefault("order", _new_order())
    design["order"].setdefault("published_price", None)
    design.setdefault("share_token", None)
    design.setdefault("approval", None)
    design.setdefault("engraving", "")
    design.setdefault("progress", None)
    return design


def save_design(design):
    with _lock:
        _write_json(design_dir(design["id"]) / "design.json", design)


def update_design(design_id, **fields):
    with _lock:
        design = load_design(design_id)
        design.update(fields)
        design["updated_at"] = time.time()
        _write_json(design_dir(design_id) / "design.json", design)
        return design


def delete_design(design_id):
    """Remove a design with its files (images, models, signature). The client link stops working."""
    with _lock:
        folder = design_dir(design_id)
        if not (folder / "design.json").exists():
            raise KeyError(design_id)
        shutil.rmtree(folder)


def ensure_share_token(design_id):
    with _lock:
        design = load_design(design_id)
        if not design.get("share_token"):
            design["share_token"] = secrets.token_urlsafe(16)
            _write_json(design_dir(design_id) / "design.json", design)
        return design["share_token"]


def find_by_token(token):
    if not token or len(token) < 16:
        raise KeyError(token)
    for d in designs_dir().iterdir():
        p = d / "design.json"
        if p.exists():
            with open(p, encoding="utf-8") as f:
                design = json.load(f)
            if design.get("share_token") and secrets.compare_digest(design["share_token"], token):
                return design
    raise KeyError(token)


def list_designs(limit=100):
    items = []
    for d in designs_dir().iterdir():
        p = d / "design.json"
        if p.exists():
            items.append(load_design(d.name))
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[:limit]


def load_settings():
    path = config.DATA_DIR / "settings.json"
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if path.exists():
        with open(path, encoding="utf-8") as f:
            settings.update(json.load(f))
    return settings


def load_timings():
    """Measured step durations (seconds) per step+provider, used to estimate progress."""
    path = config.DATA_DIR / "timings.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def record_timing(key, seconds):
    with _lock:
        timings = load_timings()
        old = timings.get(key)
        # moving average: follows provider speed changes without jumping on one slow run
        timings[key] = round(seconds if old is None else old * 0.6 + seconds * 0.4, 1)
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_json(config.DATA_DIR / "timings.json", timings)


def save_settings(settings):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = load_settings()
    merged.update({k: v for k, v in settings.items() if k in DEFAULT_SETTINGS})
    _write_json(config.DATA_DIR / "settings.json", merged)
    return merged
