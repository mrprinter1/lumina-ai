"""Design options (Hebrew labels + English prompt fragments) and prompt builders."""

OPTIONS = {
    "piece": {
        "label": "סוג התכשיט",
        "items": [
            {"id": "engagement", "he": "טבעת אירוסין", "en": "engagement ring"},
            {"id": "wedding", "he": "טבעת נישואין", "en": "wedding band"},
        ],
    },
    "metal": {
        "label": "צבע זהב",
        "items": [
            {"id": "yellow", "he": "זהב צהוב", "en": "polished yellow gold"},
            {"id": "white", "he": "זהב לבן", "en": "polished white gold"},
            {"id": "rose", "he": "זהב אדום (רוז)", "en": "polished rose gold"},
        ],
    },
    "karat": {
        "label": "קראטים (זהב)",
        "items": [
            {"id": "14K", "he": "14K", "en": "14K"},
            {"id": "18K", "he": "18K", "en": "18K"},
        ],
    },
    "shape": {
        "label": "צורת האבן",
        "items": [
            {"id": "round", "he": "עגול", "en": "round brilliant cut", "blurb": "הברק הגבוה ביותר. הבחירה הקלאסית.", "dims_1ct": [6.4, 6.4]},
            {"id": "oval", "he": "אובל", "en": "oval cut", "blurb": "מאריך את האצבע ונראה גדול יותר מעגול באותו משקל.", "dims_1ct": [7.7, 5.7]},
            {"id": "emerald", "he": "אמרלד", "en": "emerald cut", "blurb": "חיתוך מדרגות: שקיפות מראה ומראה נקי ואלגנטי.", "dims_1ct": [6.5, 4.6]},
            {"id": "cushion", "he": "קושן", "en": "cushion cut", "blurb": "פינות מעוגלות ומראה רך ורומנטי.", "dims_1ct": [5.6, 5.6]},
            {"id": "pear", "he": "טיפה", "en": "pear cut", "blurb": "נקודה מצד אחד, מאריך את האצבע.", "dims_1ct": [8.0, 5.5]},
            {"id": "princess", "he": "פרינסס", "en": "princess cut", "blurb": "ריבוע מודרני עם ברק חזק.", "dims_1ct": [5.5, 5.5]},
            {"id": "marquise", "he": "מרקיזה", "en": "marquise cut", "blurb": "מוארך עם שתי נקודות, נראה גדול מאוד.", "dims_1ct": [10.0, 5.0]},
            {"id": "radiant", "he": "רדיאנט", "en": "radiant cut", "blurb": "פינות חתוכות וברק של עגול בצורה מלבנית.", "dims_1ct": [6.2, 5.2]},
        ],
    },
    "carat": {
        "label": "גודל האבן",
        "items": [
            {"id": "0.5", "he": "0.5 קראט", "en": "0.5 carat"},
            {"id": "1", "he": "1 קראט", "en": "1 carat"},
            {"id": "1.5", "he": "1.5 קראט", "en": "1.5 carat"},
            {"id": "2", "he": "2 קראט", "en": "2 carat"},
            {"id": "3", "he": "3 קראט", "en": "3 carat"},
        ],
    },
    "setting": {
        "label": "שיבוץ",
        "items": [
            {"id": "4prong", "he": "סוליטר 4 שיניים", "en": "classic 4-prong solitaire setting"},
            {"id": "6prong", "he": "סוליטר 6 שיניים", "en": "6-prong solitaire setting"},
            {"id": "bezel", "he": "כוס (Bezel)", "en": "bezel setting"},
            {"id": "halo", "he": "הילה", "en": "halo setting with a ring of small diamonds around the center stone"},
            {"id": "hidden_halo", "he": "הילה נסתרת", "en": "hidden halo under the center stone"},
            {"id": "three_stone", "he": "שלוש אבנים", "en": "three-stone setting"},
            {"id": "cathedral", "he": "כתפיים מוגבהות", "en": "cathedral setting with raised shoulders"},
        ],
    },
    "band": {
        "label": "חישוק",
        "items": [
            {"id": "thin", "he": "חלק דק", "en": "thin plain polished band, about 1.8 mm wide"},
            {"id": "classic", "he": "חלק קלאסי", "en": "classic plain comfort-fit band, about 2.5 mm wide"},
            {"id": "pave", "he": "משובץ (פאווה)", "en": "pavé band set with small diamonds"},
            {"id": "twisted", "he": "מפותל", "en": "twisted rope band"},
            {"id": "knife", "he": "סכין", "en": "knife-edge band"},
            {"id": "split", "he": "מפוצל", "en": "split shank band"},
        ],
    },
}

DEFAULTS = {"piece": "engagement", "metal": "yellow", "karat": "14K", "shape": "round",
            "carat": "1", "setting": "4prong", "band": "thin"}

# Approximate diameters of round brilliants (mm). Other shapes are left to the jeweler.
ROUND_MM = {"0.5": 5.1, "1": 6.4, "1.5": 7.4, "2": 8.1, "3": 9.3}

# Shared photography framing: the approved image is also the source for 3D, so it must be
# a single ring on a plain background from a consistent three-quarter angle.
FRAMING = ("Professional jewelry product photo, single ring only, no hand, no box, three-quarter view "
           "from slightly above so the band, shoulders and head are all visible, centered, the whole ring "
           "in frame, pure white seamless background, soft even studio lighting, sharp focus, photorealistic, "
           "realistic proportions that a jeweler could manufacture.")

STONELESS_EDIT = ("Edit this image: remove the center stone and ALL other gemstones completely, including any "
                  "small side, halo or pavé diamonds. Keep the ring EXACTLY the same: same band, same prongs, "
                  "same proportions, same metal color, same camera angle and framing. Show the empty setting "
                  "with open prongs and the empty seats visible where the stones were. Do not add any stone, "
                  "glass, filler or new decoration. Pure white background, single ring only, even soft lighting.")


def _en(category, value):
    for item in OPTIONS[category]["items"]:
        if item["id"] == value:
            return item["en"]
    raise ValueError("unknown %s: %s" % (category, value))


def he(category, value):
    for item in OPTIONS[category]["items"]:
        if item["id"] == value:
            return item["he"]
    return value


def normalize(selections):
    sel = dict(DEFAULTS)
    for k, v in (selections or {}).items():
        if k in OPTIONS:
            _en(k, v)  # validates
            sel[k] = v
    return sel


def client_prompt(sel, free_text="", engraving=""):
    parts = [
        "A %s %s." % (_en("metal", sel["metal"]), _en("piece", sel["piece"])),
        "Center stone: %s %s diamond." % (_en("carat", sel["carat"]), _en("shape", sel["shape"])),
        "Setting: %s." % _en("setting", sel["setting"]),
        "Band: %s." % _en("band", sel["band"]),
    ]
    if free_text.strip():
        parts.append("Custom details requested by the client: %s." % free_text.strip())
    if engraving.strip():
        # shown in the picture only; the 3D model can't carry fine engraving, the jeweler adds it
        parts.append('Fine engraving on the inside of the band reading "%s".' % engraving.strip())
    parts.append(FRAMING)
    return " ".join(parts)
