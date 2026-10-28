"""Background pipeline: image -> (approve) -> stoneless edit -> 3D -> printable STL + spec.

Every job records a plan of steps on the design (design["progress"]) with an expected duration
per step, learned from past runs. The UI turns that into a percentage and time estimate.
"""
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import catalog, config, sizes, store
from .providers import images, model3d
from .ring import postprocess

log = logging.getLogger("lumina.jobs")
_api_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="api")
VIEW_COLORS = {"yellow": (212, 175, 55), "white": (215, 215, 220), "rose": (214, 150, 130)}
_mesh_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesh")  # mesh work is CPU/RAM heavy

STEP_LABELS = {
    "image": "יוצרים את ההדמיה",
    "stoneless": "מסירים את האבנים מהתמונה",
    "model3d": "בונים מודל תלת-ממד",
    "mesh": "מכינים קובץ ייצור (STL)",
}
# First-run guesses (seconds); replaced by measured averages after each run.
DEFAULT_SECONDS = {"image": 40, "stoneless": 40, "model3d": 190, "mesh": 60}
PIAPI_STATUS = {"pending": "ממתינים בתור לשרת התלת-ממד", "staged": "ממתינים בתור לשרת התלת-ממד",
                "processing": "בונים מודל תלת-ממד"}


def _provider_of(key):
    if key in ("image", "stoneless"):
        return images.get_provider().name
    if key == "model3d":
        return model3d.get_provider().name
    return "local"


def _expected(key, provider):
    measured = store.load_timings().get("%s:%s" % (key, provider))
    if measured:
        return measured
    if provider == "mock":
        return max(1.0, config.MOCK_DELAY)
    return DEFAULT_SECONDS[key]


def _plan(keys):
    steps = []
    for k in keys:
        provider = _provider_of(k)
        steps.append({"key": k, "label": STEP_LABELS[k], "provider": provider, "expected_s": _expected(k, provider),
                      "state": "pending", "started_at": None, "ended_at": None, "pct": None})
    return {"steps": steps, "started_at": time.time()}


def _set_step(design_id, key, **fields):
    """Update one step of the current plan; returns the design."""
    d = store.load_design(design_id)
    progress = d.get("progress") or _plan([key])
    for s in progress["steps"]:
        if s["key"] == key:
            s.update(fields)
            label = s["label"]
    return store.update_design(design_id, progress=progress, step=fields.get("label", label))


def _begin(design_id, key):
    return _set_step(design_id, key, state="active", started_at=time.time())


def _finish(design_id, key):
    d = store.load_design(design_id)
    for s in (d.get("progress") or {}).get("steps", []):
        if s["key"] == key and s.get("started_at"):
            store.record_timing("%s:%s" % (key, s["provider"]), time.time() - s["started_at"])
    return _set_step(design_id, key, state="done", ended_at=time.time(), pct=100)


def _guard(fn):
    def run(design_id, *args):
        try:
            fn(design_id, *args)
        except Exception as e:  # surface every failure on the design itself
            log.error("job %s failed: %s", design_id, traceback.format_exc())
            d = store.load_design(design_id)
            progress = d.get("progress")
            if progress:
                for s in progress["steps"]:
                    if s["state"] == "active":
                        s["state"] = "error"
            store.update_design(design_id, status="error", error=str(e), progress=progress)
    return run


@_guard
def _image(design_id):
    store.update_design(design_id, status="working", error=None)
    d = _begin(design_id, "image")
    sel = catalog.normalize(d["selections"])
    png = images.get_provider().generate(catalog.client_prompt(sel, d["free_text"], d.get("engraving", "")))
    name = "image_%d.png" % (len(d["images"]) + 1)
    (store.design_dir(design_id) / name).write_bytes(png)
    _finish(design_id, "image")
    store.update_design(design_id, status="image_ready", step="", images=d["images"] + [name], image=name,
                        stoneless_image=None, spec=None, glb_source=None)


@_guard
def _production(design_id):
    store.update_design(design_id, status="working", error=None, spec=None)
    d = _begin(design_id, "stoneless")
    folder = store.design_dir(design_id)
    png = images.get_provider().edit((folder / d["image"]).read_bytes(), catalog.STONELESS_EDIT)
    (folder / "stoneless.png").write_bytes(png)
    store.update_design(design_id, stoneless_image="stoneless.png")
    _finish(design_id, "stoneless")

    _begin(design_id, "model3d")
    provider = model3d.get_provider()

    def progress(status, pct=None):
        label = PIAPI_STATUS.get(status, STEP_LABELS["model3d"])
        _set_step(design_id, "model3d", label=label, pct=pct)

    glb = provider.generate(png, progress=progress)
    (folder / "source.glb").write_bytes(glb)
    store.update_design(design_id, glb_source=provider.name)
    _finish(design_id, "model3d")
    _mesh_pool.submit(_process, design_id)


@_guard
def _process(design_id):
    store.update_design(design_id, status="working", error=None)
    d = _begin(design_id, "mesh")
    settings = store.load_settings()
    inner_d = sizes.inner_diameter_mm(d["ring_size"], settings["size_system"])
    spec = postprocess.process(store.design_dir(design_id) / "source.glb", store.design_dir(design_id),
                               inner_d, shrink=float(settings["wax_shrink"]),
                               densities=settings["densities"], name="ring",
                               view_color=VIEW_COLORS[catalog.normalize(d["selections"])["metal"]])
    spec["size_system"] = settings["size_system"]
    spec["ring_size"] = d["ring_size"]
    _finish(design_id, "mesh")
    store.update_design(design_id, status="done", step="", spec=spec)


def _start(design_id, keys, pool, fn):
    store.update_design(design_id, status="queued", step="בתור", error=None, progress=_plan(keys))
    pool.submit(fn, design_id)


def start_image(design_id):
    _start(design_id, ["image"], _api_pool, _image)


def start_production(design_id):
    _start(design_id, ["stoneless", "model3d", "mesh"], _api_pool, _production)


def start_process_uploaded(design_id, source="upload"):
    store.update_design(design_id, glb_source=source)
    _start(design_id, ["mesh"], _mesh_pool, _process)


def quote(design, settings):
    """Price build-up: gold (from the processed volume) + stone + labor, plus margin.

    final_price is what the jeweler charges (their own price, or the computed one).
    published is what the client currently sees; it changes only when the jeweler sends it.
    """
    spec = design.get("spec") or {}
    order = design.get("order") or {}
    sel = catalog.normalize(design["selections"])
    alloy = "%s %s gold" % (sel["karat"], sel["metal"])
    weight = (spec.get("estimated_metal_weight_g") or {}).get(alloy)
    prices = settings["gold_price_per_gram"]
    price_g = float(prices.get("%s %s" % (sel["karat"], sel["metal"])) or prices.get(sel["karat"]) or 0)
    labor = float(settings.get("labor_cost") or 0)
    stone = float(order.get("stone_price") or 0)
    margin = float(settings.get("margin_percent") or 0)
    gold_cost = round(weight * price_g) if weight and price_g else None
    cost = (gold_cost or 0) + stone + labor
    computed = round(cost * (1 + margin / 100.0)) if gold_cost else None
    override = order.get("price_override")
    final = float(override) if override not in (None, "", 0) else computed
    deposit = float(order.get("deposit") or 0)
    published = order.get("published_price")
    return {
        "alloy": alloy, "weight_g": weight, "gold_price_per_gram": price_g or None,
        "gold_cost": gold_cost, "stone_price": stone or None, "labor_cost": labor or None,
        "margin_percent": margin, "computed_price": computed, "final_price": final,
        "deposit": deposit or None, "balance": (final - deposit) if final else None,
        "currency": settings["currency"],
        "stone_mm": catalog.ROUND_MM.get(sel["carat"]) if sel["shape"] == "round" else None,
        "published": published,
        "published_stale": bool(published and final and float(published["total"]) != float(final)),
    }
