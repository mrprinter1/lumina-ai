"""Image -> 3D providers. Each returns GLB bytes."""
import base64
import time

import httpx

from .. import config


class Mock3D:
    """Returns a bundled sample ring so the pipeline can be exercised offline."""
    name = "mock"

    def generate(self, image_png, progress=None):
        steps = int(config.MOCK_DELAY)
        for i in range(steps):
            if progress:
                progress("processing", round(100 * i / steps))
            time.sleep(1)
        return (config.SAMPLES_DIR / "sample_ring_no_stone.glb").read_bytes()


class PiAPI3D:
    """TRELLIS.2 hosted by PiAPI (https://piapi.ai/docs/trellis2-api/create-task)."""
    name = "piapi-trellis2"
    url = "https://api.piapi.ai/api/v1/task"

    def __init__(self, key, image_format):
        self.headers = {"x-api-key": key}
        self.image_format = image_format

    def generate(self, image_png, progress=None, timeout_s=900):
        b64 = base64.b64encode(image_png).decode()
        image = "data:image/png;base64," + b64 if self.image_format == "datauri" else b64
        r = httpx.post(self.url, headers=self.headers, timeout=120, json={
            "model": "Qubico/trellis2", "task_type": "image-to-3d", "input": {"image": image, "seed": 0}})
        if r.status_code >= 400:
            raise RuntimeError("PiAPI create task %s: %s" % (r.status_code, r.text[:500]))
        task_id = r.json()["data"]["task_id"]

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(5)
            r = httpx.get("%s/%s" % (self.url, task_id), headers=self.headers, timeout=60)
            if r.status_code >= 400:
                raise RuntimeError("PiAPI poll %s: %s" % (r.status_code, r.text[:500]))
            data = r.json()["data"]
            status = str(data.get("status", "")).lower()
            if progress:
                progress(status, _percent(data))
            if status == "completed":
                url = data["output"]["model_file"]
                return httpx.get(url, timeout=300, follow_redirects=True).content
            if status == "failed":
                raise RuntimeError("PiAPI task failed: %s" % (data.get("error") or data))
        raise RuntimeError("PiAPI task %s timed out" % task_id)


def _percent(data):
    """PiAPI doesn't document a progress field; use one if the task reports it, else None."""
    for src in (data, data.get("output") or {}):
        v = src.get("progress") if isinstance(src, dict) else None
        if isinstance(v, (int, float)) and 0 < v <= 100:
            return round(v)
    return None


def get_provider():
    choice = config.MODEL3D_PROVIDER
    if choice == "piapi" or (choice == "auto" and config.PIAPI_KEY):
        return PiAPI3D(config.PIAPI_KEY, config.PIAPI_IMAGE_FORMAT)
    return Mock3D()
