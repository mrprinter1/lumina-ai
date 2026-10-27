"""Ring size -> finger-hole (inner) diameter in mm."""
import math

SYSTEMS = {
    # Assumed Israeli convention: size number = inner circumference in mm (ISO 8653).
    # Not yet confirmed with a jeweler.
    "circumference": "היקף פנימי במ\"מ (ISO, מקובל בישראל)",
    "us": "מידות אמריקאיות (US)",
    "diameter": "קוטר פנימי במ\"מ",
}


def inner_diameter_mm(size, system):
    size = float(size)
    if system == "circumference":
        return size / math.pi
    if system == "us":
        return 11.63 + 0.8128 * size
    if system == "diameter":
        return size
    raise ValueError("unknown size system: %s" % system)
