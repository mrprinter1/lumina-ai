#!/usr/bin/env python3
"""Generate the option photos shown in the studio picker (stone shapes, settings, bands).

One-time job: each photo is saved to web/catalog/<category>/<id>.jpg and served as a static file, so using the
site costs nothing extra. Needs OPENAI_API_KEY (and optionally OPENAI_IMAGE_MODEL) in .env.

    .venv/bin/python scripts/make_catalog_images.py --dry-run      # list the prompts, spend nothing
    .venv/bin/python scripts/make_catalog_images.py --only shape   # one category first, to judge the look
    .venv/bin/python scripts/make_catalog_images.py                # everything that is missing (~21 photos)
    .venv/bin/python scripts/make_catalog_images.py --ids round,halo --force   # redo specific photos

The photos are shot on pure black; the page blends them onto its dark background.
"""
import argparse
import base64
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

from app import catalog, config  # noqa: E402

OUT = os.path.join(ROOT, "web", "catalog")
SIZE = 640

COMMON = ("pure black seamless background, dramatic soft studio lighting with crisp highlights, photorealistic "
          "luxury jewelry catalog photograph, sharp focus, centered with space around it, no text, no watermark, "
          "no hands, no box")

TEMPLATES = {
    "shape": ("Macro studio photograph of a single loose {en} diamond, perfectly clear and colorless, floating, viewed "
              "from slightly above at a three-quarter angle so the table, crown facets and pavilion are visible, "
              "brilliant white sparkle and spectral fire, " + COMMON + "."),
    "setting": ("Studio photograph of a polished white gold engagement ring with a {en}, a one carat round brilliant "
                "diamond as the center stone, three-quarter view from slightly above, the head and how the stone is "
                "held clearly visible, single ring only, " + COMMON + "."),
    "band": ("Studio photograph of a {en}, polished white gold, no center stone and no setting, standing upright in "
             "a three-quarter view that shows the band's profile and surface detail, single ring only, "
             + COMMON + "."),
}


def jobs(only, ids):
    for key in ("shape", "setting", "band"):
        if only and key != only:
            continue
        for item in catalog.OPTIONS[key]["items"]:
            if ids and item["id"] not in ids:
                continue
            yield key, item["id"], TEMPLATES[key].format(en=item["en"])


def generate(prompt, quality):
    body = {"model": config.OPENAI_IMAGE_MODEL, "prompt": prompt, "size": "1024x1024", "n": 1}
    if quality:
        body["quality"] = quality
    headers = {"Authorization": "Bearer " + config.OPENAI_API_KEY}
    for attempt in range(3):
        r = httpx.post("https://api.openai.com/v1/images/generations", headers=headers, json=body, timeout=300)
        if r.status_code in (429, 500, 502, 503) and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code >= 400:
            raise RuntimeError("OpenAI %s: %s" % (r.status_code, r.text[:300]))
        return base64.b64decode(r.json()["data"][0]["b64_json"])


def save(png, path):
    img = Image.open(io.BytesIO(png)).convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "JPEG", quality=86, optimize=True, progressive=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["shape", "setting", "band"])
    ap.add_argument("--ids", help="comma-separated option ids")
    ap.add_argument("--force", action="store_true", help="redo photos that already exist")
    ap.add_argument("--dry-run", action="store_true", help="print the prompts and stop")
    ap.add_argument("--quality", choices=["low", "medium", "high", "auto"], help="image quality (more is pricier)")
    args = ap.parse_args()

    todo = []
    for key, id_, prompt in jobs(args.only, set(args.ids.split(",")) if args.ids else None):
        path = os.path.join(OUT, key, id_ + ".jpg")
        if os.path.exists(path) and not args.force:
            continue
        todo.append((key, id_, prompt, path))
    if not todo:
        print("Nothing to do: all photos exist (use --force to redo).")
        return 0
    print("%d photo(s) to make with model %s" % (len(todo), config.OPENAI_IMAGE_MODEL))
    if args.dry_run:
        for key, id_, prompt, _ in todo:
            print("\n[%s/%s]\n%s" % (key, id_, prompt))
        return 0
    if not config.OPENAI_API_KEY:
        print("OPENAI_API_KEY is not set in .env", file=sys.stderr)
        return 1

    failed = []

    def run(job):
        key, id_, prompt, path = job
        try:
            save(generate(prompt, args.quality), path)
            print("  ok   %s/%s" % (key, id_), flush=True)
        except Exception as e:  # keep going: one failure should not waste the others
            failed.append((key, id_))
            print("  FAIL %s/%s: %s" % (key, id_, e), flush=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, todo))
    print("\nDone: %d made, %d failed.%s" % (len(todo) - len(failed), len(failed),
                                            " Run again to retry the failed ones." if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
