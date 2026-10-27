"""Image generation + editing providers. Each returns PNG bytes."""
import base64
import io

import httpx
from PIL import Image, ImageDraw

from .. import config


class MockImages:
    """Offline stand-in so the whole flow runs without API keys."""
    name = "mock"

    def _draw(self, label, with_stone):
        img = Image.new("RGB", (1024, 1024), "white")
        d = ImageDraw.Draw(img)
        d.ellipse((262, 300, 762, 800), outline=(196, 160, 60), width=40)
        if with_stone:
            d.polygon([(512, 180), (600, 260), (512, 330), (424, 260)], fill=(200, 225, 240), outline=(120, 140, 160))
        for x in (440, 584):
            d.line((x, 330, x, 220), fill=(196, 160, 60), width=14)
        d.text((24, 24), "MOCK IMAGE - " + label, fill=(120, 120, 120))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def generate(self, prompt):
        return self._draw("set OPENAI_API_KEY for real images", True)

    def edit(self, image_png, prompt):
        return self._draw("stone removed", False)


class OpenAIImages:
    name = "openai"
    base = "https://api.openai.com/v1/images"

    def __init__(self, key, model):
        self.headers = {"Authorization": "Bearer " + key}
        self.model = model

    @staticmethod
    def _png(resp):
        if resp.status_code >= 400:
            raise RuntimeError("OpenAI image API %s: %s" % (resp.status_code, resp.text[:500]))
        return base64.b64decode(resp.json()["data"][0]["b64_json"])

    def generate(self, prompt):
        r = httpx.post(self.base + "/generations", headers=self.headers, timeout=300,
                       json={"model": self.model, "prompt": prompt, "size": "1024x1024", "n": 1})
        return self._png(r)

    def edit(self, image_png, prompt):
        r = httpx.post(self.base + "/edits", headers=self.headers, timeout=300,
                       files={"image": ("ring.png", image_png, "image/png")},
                       data={"model": self.model, "prompt": prompt, "size": "1024x1024"})
        return self._png(r)


def get_provider():
    choice = config.IMAGE_PROVIDER
    if choice == "openai" or (choice == "auto" and config.OPENAI_API_KEY):
        return OpenAIImages(config.OPENAI_API_KEY, config.OPENAI_IMAGE_MODEL)
    return MockImages()
