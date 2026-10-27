"""Background pipeline: image -> (approve) -> stoneless edit -> 3D -> printable STL + spec."""
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import catalog, sizes, store
from .providers import images, model3d
from .ring import postprocess

log = logging.getLogger("lumina.jobs")
_api_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="api")
VIEW_COLORS = {"yellow": (212, 175, 55), "white": (215, 215, 220), "rose": (214, 150, 130)}
_mesh_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesh")  # mesh work is CPU/RAM heavy


def _guard(fn):
    def run(design_id, *args):
        try:
            fn(design_id, *args)
        except Exception as e:  # surface every failure on the design itself
            log.error("job %s failed: %s", design_id, traceback.format_exc())
            store.update_design(design_id, status="error", error=str(e))
    return run


@_guard
def _image(design_id):
    d = store.update_design(design_id, status="working", step="יוצר תמונה", error=None)
    sel = catalog.normalize(d["selections"])
    png = images.get_provider().generate(catalog.client_prompt(sel, d["free_text"]))
    name = "image_%d.png" % (len(d["images"]) + 1)
    (store.design_dir(design_id) / name).write_bytes(png)
    store.update_design(design_id, status="image_ready", step="", images=d["images"] + [name], image=name,
                        stoneless_image=None, spec=None)


@_guard
def _production(design_id):
    d = store.update_design(design_id, status="working", step="מסיר את האבן מהתמונה", error=None, spec=None)
    folder = store.design_dir(design_id)
    png = images.get_provider().edit((folder / d["image"]).read_bytes(), catalog.STONELESS_EDIT)
    (folder / "stoneless.png").write_bytes(png)
    store.update_design(design_id, stoneless_image="stoneless.png", step="יוצר מודל תלת-ממד")

    provider = model3d.get_provider()
    glb = provider.generate(png, progress=lambda s: store.update_design(
        design_id, step="יוצר מודל תלת-ממד (%s)" % s))
    (folder / "source.glb").write_bytes(glb)
    store.update_design(design_id, glb_source=provider.name)
    _mesh_pool.submit(_process, design_id)


@_guard
def _process(design_id):
    d = store.update_design(design_id, status="working", step="מכין קובץ להדפסה (STL)", error=None)
    settings = store.load_settings()
    inner_d = sizes.inner_diameter_mm(d["ring_size"], settings["size_system"])
    spec = postprocess.process(store.design_dir(design_id) / "source.glb", store.design_dir(design_id),
                               inner_d, shrink=float(settings["wax_shrink"]),
                               densities=settings["densities"], name="ring",
                               view_color=VIEW_COLORS[catalog.normalize(d["selections"])["metal"]])
    spec["size_system"] = settings["size_system"]
    spec["ring_size"] = d["ring_size"]
    store.update_design(design_id, status="done", step="", spec=spec)


def start_image(design_id):
    store.update_design(design_id, status="queued", step="בתור", error=None)
    _api_pool.submit(_image, design_id)


def start_production(design_id):
    store.update_design(design_id, status="queued", step="בתור", error=None)
    _api_pool.submit(_production, design_id)


def start_process_uploaded(design_id):
    store.update_design(design_id, status="queued", step="בתור", error=None, glb_source="upload")
    _mesh_pool.submit(_process, design_id)


def quote(design, settings):
    """Price build-up: gold (from the processed volume) + stone + labor, plus margin."""
    spec = design.get("spec") or {}
    order = design.get("order") or {}
    sel = catalog.normalize(design["selections"])
    alloy = "%s %s gold" % (sel["karat"], sel["metal"])
    weight = (spec.get("estimated_metal_weight_g") or {}).get(alloy)
    price_g = float(settings["gold_price_per_gram"].get(sel["karat"], 0) or 0)
    labor = float(settings.get("labor_cost") or 0)
    stone = float(order.get("stone_price") or 0)
    margin = float(settings.get("margin_percent") or 0)
    gold_cost = round(weight * price_g) if weight and price_g else None
    cost = (gold_cost or 0) + stone + labor
    computed = round(cost * (1 + margin / 100.0)) if gold_cost else None
    override = order.get("price_override")
    final = float(override) if override not in (None, "", 0) else computed
    deposit = float(order.get("deposit") or 0)
    return {
        "alloy": alloy, "weight_g": weight, "gold_price_per_gram": price_g or None,
        "gold_cost": gold_cost, "stone_price": stone or None, "labor_cost": labor or None,
        "margin_percent": margin, "computed_price": computed, "final_price": final,
        "deposit": deposit or None, "balance": (final - deposit) if final else None,
        "currency": settings["currency"],
        "stone_mm": catalog.ROUND_MM.get(sel["carat"]) if sel["shape"] == "round" else None,
    }
