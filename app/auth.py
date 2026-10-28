"""Studio password. Client links (/o/<token>, /api/client/..., /c/...) stay public; everything else needs a login.

One shared password from STUDIO_PASSWORD. Without it the app is open (fine on your own computer, not on the internet).
The session is a signed, expiring cookie. This is a stopgap until real accounts exist.
"""
import hashlib
import hmac
import os
import secrets
import time

from . import config

COOKIE = "lumina_session"
SESSION_DAYS = 30
MAX_FAILS, WINDOW_S, MAX_FAILS_ALL = 5, 300, 40

# Only what a client needs to see their link: the page, its data, its image, and the shared assets.
PUBLIC_PREFIXES = ("/o/", "/api/client/", "/c/", "/vendor/", "/login", "/logout")
PUBLIC_FILES = {"/style.css", "/fx.js", "/sign.js", "/brand/logo", "/favicon.ico"}

_fails = {}


def enabled():
    return bool(config.STUDIO_PASSWORD)


def _secret():
    path = config.DATA_DIR / ".session_secret"
    if path.exists():
        return path.read_bytes()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


def is_public(path):
    return path in PUBLIC_FILES or path.startswith(PUBLIC_PREFIXES)


def make_cookie():
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(_secret(), (exp + config.STUDIO_PASSWORD).encode(), hashlib.sha256).hexdigest()
    return "%s.%s" % (exp, sig)


def valid_cookie(value):
    try:
        exp, sig = (value or "").split(".", 1)
        if int(exp) < time.time():
            return False
    except ValueError:
        return False
    want = hmac.new(_secret(), (exp + config.STUDIO_PASSWORD).encode(), hashlib.sha256).hexdigest()
    # includes the password in the signature, so changing the password logs everyone out
    return hmac.compare_digest(sig, want)


def client_ip(request):
    """The caller's address; behind a tunnel or proxy that is in a forwarded header."""
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "?")


def locked_out(ip):
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < WINDOW_S]
    _fails[ip] = recent
    # a forwarded address can be forged, so a global cap backs up the per-address one
    total = sum(1 for ts in _fails.values() for t in ts if now - t < WINDOW_S)
    return len(recent) >= MAX_FAILS or total >= MAX_FAILS_ALL


def check_password(ip, attempt):
    if locked_out(ip):
        return False
    ok = hmac.compare_digest(attempt.encode(), config.STUDIO_PASSWORD.encode())
    if not ok:
        _fails.setdefault(ip, []).append(time.time())
    else:
        _fails.pop(ip, None)
    return ok
