"""Lumina prototype server. Run: .venv/bin/uvicorn app.main:app --port 8000"""
import base64
import html
import logging
import re
import time
from urllib.parse import quote as urlquote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, catalog, config, jobs, sizes, store
from .providers import images, model3d

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Lumina")
FILE_RE = re.compile(r"^(image_\d+\.png|stoneless\.png|ring\.stl|ring_view\.glb|source\.glb|signature\.png)$")
BUSY = ("queued", "working")


@app.on_event("startup")
def warn_if_open():
    if not auth.enabled():
        logging.getLogger("lumina").warning(
            "STUDIO_PASSWORD is not set: the studio is open to anyone who can reach this address.")


@app.on_event("startup")
def recover_interrupted_jobs():
    # jobs run in this process; after a restart nothing will finish them, so say so instead of loading forever
    for d in store.list_designs(limit=10_000):
        if d["status"] in BUSY:
            store.update_design(d["id"], status="error", step="",
                                error="השרת הופעל מחדש באמצע העבודה. לחצו שוב כדי להמשיך.")


@app.middleware("http")
async def require_login(request, call_next):
    path = request.url.path
    if auth.enabled() and not auth.is_public(path) and not auth.valid_cookie(request.cookies.get(auth.COOKIE)):
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/login?next=" + urlquote(path), status_code=303)
        return JSONResponse({"detail": "צריך להתחבר מחדש"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def revalidate_static(request, call_next):
    # The UI changes often; make browsers revalidate pages and scripts instead of using stale copies.
    response = await call_next(request)
    if not request.url.path.startswith(("/files/", "/c/")):
        response.headers["Cache-Control"] = "no-cache"
    return response


class NewDesign(BaseModel):
    selections: dict = {}
    free_text: str = ""
    engraving: str = ""
    ring_size: float
    client: dict = {}


class OrderUpdate(BaseModel):
    client: dict = None
    stage: str = None
    stone_price: float = None
    price_override: float = None
    clear_price_override: bool = False
    deposit: float = None
    notes: str = None


class PricePublish(BaseModel):
    publish: bool = True


class Approval(BaseModel):
    name: str
    signature: str  # data:image/png;base64,...


def _get(design_id):
    try:
        return store.load_design(design_id)
    except KeyError:
        raise HTTPException(404, "design not found")


def _public(design):
    out = dict(design)
    out["quote"] = jobs.quote(design, store.load_settings())
    out["server_now"] = time.time()  # lets the browser extrapolate progress against its own clock
    return out


def _share_url(request, token):
    base = (store.load_settings().get("public_url") or str(request.base_url)).rstrip("/")
    return "%s/o/%s" % (base, token)


def _wa_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):  # local Israeli number -> international
        digits = "972" + digits[1:]
    return digits


# ---------- login ----------

LOGIN_PAGE = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>כניסה</title>
<link href="https://fonts.googleapis.com/css2?family=Bellefair&family=Heebo:wght@300;400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/style.css"></head><body>
<main class="login"><h1>Lumina</h1><p class="lede">הכניסה לסטודיו מוגנת בסיסמה.</p>
<form method="post" action="/login"><input type="hidden" name="next" value="%(next)s">
<label>סיסמה<input name="password" type="password" autocomplete="current-password" autofocus required></label>
<p class="error" role="alert">%(error)s</p>
<button class="btn primary" type="submit">כניסה</button></form></main></body></html>"""


def _safe_next(value):
    # only same-site paths, never a full URL
    return value if value.startswith("/") and not value.startswith("//") else "/"


@app.get("/login", response_class=HTMLResponse)
def login_page(next: str = "/"):
    if not auth.enabled():
        return RedirectResponse("/", status_code=303)
    return LOGIN_PAGE % {"next": html.escape(_safe_next(next)), "error": ""}


@app.post("/login")
def login(request: Request, password: str = Form(""), next: str = Form("/")):
    ip = auth.client_ip(request)
    if auth.locked_out(ip):
        return HTMLResponse(LOGIN_PAGE % {"next": html.escape(_safe_next(next)),
                                          "error": "יותר מדי ניסיונות. נסו שוב בעוד כמה דקות."}, status_code=429)
    if not auth.check_password(ip, password):
        return HTMLResponse(LOGIN_PAGE % {"next": html.escape(_safe_next(next)), "error": "הסיסמה לא נכונה."},
                            status_code=401)
    response = RedirectResponse(_safe_next(next), status_code=303)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.COOKIE, auth.make_cookie(), max_age=auth.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure)
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE)
    return response


# ---------- jeweler API ----------

@app.get("/api/meta")
def meta():
    return {"options": catalog.OPTIONS, "defaults": catalog.DEFAULTS, "size_systems": sizes.SYSTEMS,
            "stages": store.ORDER_STAGES,
            "providers": {"image": images.get_provider().name, "model3d": model3d.get_provider().name},
            "login": auth.enabled()}


@app.get("/api/settings")
def get_settings():
    return store.load_settings()


@app.put("/api/settings")
def put_settings(body: dict):
    if body.get("size_system") and body["size_system"] not in sizes.SYSTEMS:
        raise HTTPException(400, "unknown size system")
    body.pop("has_logo", None)
    return store.save_settings(body)


@app.post("/api/settings/logo")
async def upload_logo(file: UploadFile = File(...)):
    data = await file.read()
    if not data.startswith(b"\x89PNG") and not data[:3] == b"\xff\xd8\xff":
        raise HTTPException(400, "הלוגו צריך להיות PNG או JPG")
    if len(data) > 2_000_000:
        raise HTTPException(400, "הלוגו גדול מ-2MB")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (config.DATA_DIR / "logo").write_bytes(data)
    return store.save_settings({"has_logo": True})


@app.get("/brand/logo")
def logo():
    path = config.DATA_DIR / "logo"
    if not path.exists():
        raise HTTPException(404)
    media = "image/png" if path.read_bytes()[:4] == b"\x89PNG" else "image/jpeg"
    return FileResponse(path, media_type=media)


@app.post("/api/designs")
def create(body: NewDesign):
    try:
        sel = catalog.normalize(body.selections)
    except ValueError as e:
        raise HTTPException(400, str(e))
    client = {k: str(body.client.get(k, ""))[:120] for k in ("name", "phone")}
    design = store.create_design(sel, body.free_text[:1000], body.ring_size, client, body.engraving.strip()[:60])
    jobs.start_image(design["id"])
    return _public(store.load_design(design["id"]))


@app.get("/api/designs")
def list_all():
    return [_public(d) for d in store.list_designs()]


@app.get("/api/designs/{design_id}")
def get_one(design_id: str):
    return _public(_get(design_id))


class Regenerate(BaseModel):
    selections: dict = None
    free_text: str = None
    engraving: str = None
    ring_size: float = None


@app.post("/api/designs/{design_id}/regenerate")
def regenerate(design_id: str, body: Regenerate = None):
    d = _get(design_id)
    if d["status"] in BUSY:
        raise HTTPException(409, "already working")
    if d.get("approval"):
        raise HTTPException(409, "הלקוח כבר אישר את העיצוב")
    changes = {}
    if body and body.selections is not None:
        try:
            changes["selections"] = catalog.normalize(body.selections)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if body and body.free_text is not None:
        changes["free_text"] = body.free_text[:1000]
    if body and body.engraving is not None:
        changes["engraving"] = body.engraving.strip()[:60]
    if body and body.ring_size is not None:
        changes["ring_size"] = body.ring_size
    if changes:
        # new look or size -> any previous production files no longer match
        store.update_design(design_id, spec=None, stoneless_image=None, **changes)
    jobs.start_image(design_id)
    return _public(_get(design_id))


@app.post("/api/designs/{design_id}/produce")
def produce(design_id: str):
    d = _get(design_id)
    if d["status"] in BUSY or not d["image"]:
        raise HTTPException(409, "no finished image")
    jobs.start_production(design_id)
    return _public(_get(design_id))


@app.post("/api/designs/{design_id}/reprocess")
def reprocess(design_id: str):
    """Rebuild the STL from the 3D model already received (after a settings change or a processing fix)."""
    d = _get(design_id)
    if d["status"] in BUSY:
        raise HTTPException(409, "already working")
    if not (store.design_dir(design_id) / "source.glb").exists():
        raise HTTPException(409, "אין עדיין מודל תלת-ממד לעיבוד")
    jobs.start_process_uploaded(design_id, source=d.get("glb_source") or "upload")
    return _public(_get(design_id))


@app.patch("/api/designs/{design_id}/order")
def update_order(design_id: str, body: OrderUpdate):
    d = _get(design_id)
    order, client = dict(d["order"]), dict(d["client"])
    if body.client is not None:
        client.update({k: str(body.client.get(k, client.get(k, "")))[:120] for k in ("name", "phone")})
    if body.stage is not None:
        if body.stage not in store.STAGE_IDS:
            raise HTTPException(400, "unknown stage")
        order["stage"] = body.stage
    for k in ("stone_price", "deposit", "price_override"):
        v = getattr(body, k)
        if v is not None:
            if v < 0:
                raise HTTPException(400, "negative amount")
            order[k] = v
    if body.clear_price_override:
        order["price_override"] = None
    if body.notes is not None:
        order["notes"] = body.notes[:2000]
    store.update_design(design_id, order=order, client=client)
    return _public(_get(design_id))


@app.post("/api/designs/{design_id}/price")
def publish_price(design_id: str, body: PricePublish):
    """Send the jeweler's price to the client link, or take it back. Until sent, the client sees no price."""
    d = _get(design_id)
    order = dict(d["order"])
    if body.publish:
        q = jobs.quote(d, store.load_settings())
        if not q["final_price"]:
            raise HTTPException(409, "צריך לקבוע מחיר לפני השליחה ללקוח")
        order["published_price"] = {"total": q["final_price"], "currency": q["currency"], "at": time.time()}
    else:
        if d.get("approval"):
            raise HTTPException(409, "הלקוח כבר אישר את המחיר")
        order["published_price"] = None
    store.update_design(design_id, order=order)
    return _public(_get(design_id))


@app.post("/api/designs/{design_id}/share")
def share(design_id: str, request: Request):
    d = _get(design_id)
    if not d["image"]:
        raise HTTPException(409, "אין עדיין תמונה לשיתוף")
    token = store.ensure_share_token(design_id)
    d = _get(design_id)
    if d["order"]["stage"] == "design" and not d.get("approval"):
        store.update_design(design_id, order=dict(d["order"], stage="awaiting_approval"))
    s = store.load_settings()
    url = _share_url(request, token)
    text = s["share_message"].format(name=d["client"]["name"] or "", business=s["business_name"] or "הסטודיו",
                                     link=url)
    phone = _wa_phone(d["client"]["phone"])
    return {"url": url, "text": text,
            "whatsapp": "https://wa.me/%s?text=%s" % (phone, urlquote(text)),
            "is_local": "localhost" in url or "127.0.0.1" in url, "design": _public(_get(design_id))}


@app.post("/api/designs/{design_id}/upload-glb")
async def upload_glb(design_id: str, file: UploadFile = File(...)):
    if _get(design_id)["status"] in BUSY:
        raise HTTPException(409, "already working")
    data = await file.read()
    if not data.startswith(b"glTF"):
        raise HTTPException(400, "not a GLB file")
    (store.design_dir(design_id) / "source.glb").write_bytes(data)
    jobs.start_process_uploaded(design_id)
    return _public(_get(design_id))


@app.get("/files/{design_id}/{name}")
def files(design_id: str, name: str):
    if not FILE_RE.match(name):
        raise HTTPException(404)
    _get(design_id)
    path = store.design_dir(design_id) / name
    if not path.exists():
        raise HTTPException(404)
    download = name.endswith(".stl")
    return FileResponse(path, filename=("lumina_%s.stl" % design_id) if download else None)


# ---------- client (shared link) ----------

def _client_design(token):
    try:
        return store.find_by_token(token)
    except KeyError:
        raise HTTPException(404, "הקישור לא נמצא או שבוטל")


@app.get("/api/client/{token}")
def client_view(token: str):
    d = _client_design(token)
    s = store.load_settings()
    q = jobs.quote(d, s)
    sel = catalog.normalize(d["selections"])
    specs = None
    if s["client_sees_specs"]:
        specs = [
            ["סוג", catalog.he("piece", sel["piece"])],
            ["זהב", "%s %s" % (catalog.he("metal", sel["metal"]), sel["karat"])],
            ["אבן מרכזית", "%s, %s" % (catalog.he("shape", sel["shape"]), catalog.he("carat", sel["carat"]))],
            ["שיבוץ", catalog.he("setting", sel["setting"])],
            ["חישוק", catalog.he("band", sel["band"])],
            ["מידה", str(d["ring_size"]).rstrip("0").rstrip(".")],
        ]
        if d["free_text"]:
            specs.append(["בקשות מיוחדות", d["free_text"]])
        if d.get("engraving"):
            specs.append(["חריטה", d["engraving"]])
        if s["client_sees_weight"] and q["weight_g"]:
            specs.append(["משקל זהב משוער", "%s גרם" % q["weight_g"]])
    # the client sees only a price the jeweler sent, never the working figures
    price = None
    pub = d["order"].get("published_price")
    if pub:
        deposit = float(d["order"].get("deposit") or 0)
        price = {"total": pub["total"], "deposit": deposit or None, "balance": pub["total"] - deposit,
                 "currency": pub["currency"]}
    approval = d.get("approval")
    return {
        "business": {"name": s["business_name"], "phone": s["business_phone"], "has_logo": s["has_logo"]},
        "client_name": d["client"]["name"],
        "image": "/c/%s/image?v=%s" % (token, urlquote(d["image"] or "")) if d["image"] else None,
        "specs": specs, "price": price, "awaiting_price": not pub and not approval,
        "stage": d["order"]["stage"], "stages": store.ORDER_STAGES,
        "approval": {"name": approval["name"], "at": approval["at"]} if approval else None,
    }


@app.get("/c/{token}/image")
def client_image(token: str):
    d = _client_design(token)
    name = (d.get("approval") or {}).get("image") or d["image"]
    if not name:
        raise HTTPException(404)
    return FileResponse(store.design_dir(d["id"]) / name)


def _record_approval(d, body, request, channel):
    """Store a signed approval and kick off production. Shared by in-store and link approvals."""
    if d.get("approval"):
        raise HTTPException(409, "העיצוב כבר אושר")
    if not d["image"] or d["status"] in BUSY:
        raise HTTPException(409, "העיצוב עדיין לא מוכן לאישור")
    pub = d["order"].get("published_price")
    if channel == "link" and not pub:
        raise HTTPException(409, "המחיר עוד לא נשלח. אפשר לאשר אחרי שתקבלו הצעת מחיר")
    name = body.name.strip()[:120]
    if len(name) < 2:
        raise HTTPException(400, "נא לכתוב שם מלא")
    m = re.match(r"^data:image/png;base64,([A-Za-z0-9+/=]+)$", body.signature)
    if not m:
        raise HTTPException(400, "חסרה חתימה")
    sig = base64.b64decode(m.group(1))
    if not sig.startswith(b"\x89PNG") or len(sig) > 500_000:
        raise HTTPException(400, "חתימה לא תקינה")
    (store.design_dir(d["id"]) / "signature.png").write_bytes(sig)
    q = jobs.quote(d, store.load_settings())
    approval = {"name": name, "at": time.time(), "image": d["image"],
                "price": pub["total"] if pub else q["final_price"],
                "currency": pub["currency"] if pub else q["currency"], "channel": channel,
                "ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent", "")[:300]}
    store.update_design(d["id"], approval=approval, order=dict(d["order"], stage="approved"))
    if not d.get("spec"):
        jobs.start_production(d["id"])


@app.post("/api/designs/{design_id}/approve")
def approve_in_store(design_id: str, body: Approval, request: Request):
    _record_approval(_get(design_id), body, request, "in_store")
    return _public(_get(design_id))


@app.post("/api/client/{token}/approve")
def client_approve(token: str, body: Approval, request: Request):
    _record_approval(_client_design(token), body, request, "link")
    return client_view(token)


@app.get("/o/{token}", response_class=HTMLResponse)
def client_page(token: str):
    return FileResponse(config.WEB_DIR / "client.html")


# ---------- printable spec for the jeweler ----------

@app.get("/designs/{design_id}/spec", response_class=HTMLResponse)
def spec_page(design_id: str):
    d = _get(design_id)
    if not d.get("spec"):
        raise HTTPException(409, "model not ready")
    settings = store.load_settings()
    s, q, sel = d["spec"], jobs.quote(d, settings), catalog.normalize(d["selections"])
    e = html.escape
    cur = q["currency"]

    def row(k, v):
        return "<tr><th>%s</th><td>%s</td></tr>" % (e(k), e(str(v)) if v not in (None, "") else "—")

    def money(v):
        return "%s %s" % ("{:,.0f}".format(v), cur) if v else None

    dims = s["dimensions_mm"]
    rows = "".join([
        row("לקוח", " · ".join(x for x in (d["client"]["name"], d["client"]["phone"]) if x) or None),
        row("סוג", catalog.he("piece", sel["piece"])),
        row("זהב", "%s %s" % (sel["karat"], catalog.he("metal", sel["metal"]))),
        row("אבן מרכזית", "%s, %s" % (catalog.he("shape", sel["shape"]), catalog.he("carat", sel["carat"]))),
        row("קוטר אבן משוער (מ\"מ)", q["stone_mm"]),
        row("שיבוץ", catalog.he("setting", sel["setting"])),
        row("חישוק", catalog.he("band", sel["band"])),
        row("חריטה (לביצוע ידני, לא בקובץ)", d.get("engraving")),
        row("מידה", "%s (%s)" % (d["ring_size"], sizes.SYSTEMS.get(s.get("size_system"), ""))),
        row("קוטר פנימי (מ\"מ)", s["inner_diameter_after_scaling_mm"]),
        row("מידות כלליות (מ\"מ)", "%s × %s × %s" % tuple(dims)),
        row("נפח (מ\"מ³)", s["volume_mm3"]),
        row("משקל זהב משוער (גרם)", q["weight_g"]),
        row("זהב", money(q["gold_cost"])),
        row("אבן", money(q["stone_price"])),
        row("עבודה", money(q["labor_cost"])),
        row("מחיר ללקוח", money(q["final_price"])),
        row("עובי דופן (אחוזון 5, מ\"מ)", s["wall_thickness_p5_mm"]),
        row("מקדם התכווצות שעווה", s["shrink"]),
    ])
    notes = "".join("<li>%s</li>" % e(w) for w in s["warnings"])
    free = "<p><b>בקשות הלקוח:</b> %s</p>" % e(d["free_text"]) if d["free_text"] else ""
    img = '<img src="/files/%s/%s" alt="העיצוב המאושר">' % (e(design_id), e(d["image"])) if d["image"] else ""
    appr = d.get("approval")
    appr_html = ('<p class="ok">אושר על ידי %s ב-%s</p>' % (
        e(appr["name"]), time.strftime("%d/%m/%Y %H:%M", time.localtime(appr["at"])))) if appr else ""
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>כרטיס עבודה</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bellefair&family=Heebo:wght@300;400;500&display=swap" rel="stylesheet">
<style>body{font:16px/1.6 Heebo,system-ui,sans-serif;margin:0;background:#fff;color:#1f2321}main{max-width:720px;margin:0 auto;padding:28px 16px}
h1{font:400 34px/1.2 Bellefair,serif;margin:0}.n{color:#6d7370;font-size:14px}
img{width:100%%;max-width:340px;border-radius:4px;margin:16px 0}table{width:100%%;border-collapse:collapse;margin:12px 0}
th,td{text-align:right;padding:7px 4px;border-bottom:1px solid #e4e6e3;vertical-align:top}th{color:#6d7370;font-weight:400;width:45%%}
.ok{color:#2f6b4f}a.btn{display:inline-block;margin:8px 0 0 8px;padding:8px 14px;border:1px solid #1f3a33;color:#1f3a33;border-radius:4px;text-decoration:none}
@media print{a.btn{display:none}}</style></head><body><main>
<h1>כרטיס עבודה</h1><p class="n">%s · עיצוב %s</p>%s%s%s<table>%s</table>
<a class="btn" href="/files/%s/ring.stl">הורדת STL</a><a class="btn" href="javascript:print()">הדפסה / PDF</a>
<h3>הערות אוטומטיות</h3><ul class="n">%s</ul>
<p class="n">המשקל והמחיר הם הערכה לפי נפח הקובץ וצפיפות הסגסוגת, בלי איבוד ביציקה. הקובץ הוא טיוטה לייצור ודורש בדיקה.</p>
</main></body></html>""" % (e(settings["business_name"] or "Lumina"), e(design_id), appr_html, img, free, rows,
                             e(design_id), notes)


app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
