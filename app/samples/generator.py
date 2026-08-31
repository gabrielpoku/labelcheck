"""Generate sample label artwork for demos and tests.

Run:  python -m app.samples.generator
Writes PNG labels, ``index.json`` (used by the UI's sample picker), and
``applications.csv`` (used for batch demos) into the ``samples/`` directory.

The labels are drawn programmatically so every scenario is reproducible and
the expected verdict is known exactly. Scenarios cover the interesting cases
from the stakeholder interviews:

- bourbon_ok             everything matches                    -> MATCH
- bourbon_case           brand case differs ("OLD TOM distillery") -> still MATCH
- bourbon_abv_wrong      label says 43%, application says 45%   -> MISMATCH
- bourbon_warning_typo   one OCR-noisy word in the warning       -> REVIEW
- bourbon_warning_wrong  real wording change in the warning      -> MISMATCH
- wine_import            imported wine, country of origin check  -> MATCH
- wine_net_wrong         label says 500 mL, application 750 mL  -> MISMATCH
- imperfect_photo        bourbon_ok with rotation/glare/blur (bonus scenario)
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.engine.warning_text import CANONICAL_WARNING

SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"

FONT_DIRS = [
    Path("C:/Windows/Fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
]


def _load_font(bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold \
        else ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    for d in FONT_DIRS:
        for name in candidates:
            path = d / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_label(out_path: Path, *, brand: str, class_type: str, alcohol: str, net: str,
               bottler_name: str, bottler_address: str, country: str | None,
               warning: str) -> None:
    W, H = 620, 970
    img = Image.new("RGB", (W, H), "#f8f4ea")
    d = ImageDraw.Draw(img)
    ink = "#20242c"
    margin = 46
    y = 54

    def block(text: str, font, gap_after: int, center: bool = False) -> None:
        nonlocal y
        for line in _wrap(d, text, font, W - 2 * margin):
            w = d.textlength(line, font=font)
            x = (W - w) / 2 if center else margin
            d.text((x, y), line, font=font, fill=ink)
            y += font.size + 8
        y += gap_after

    d.rectangle([margin - 14, 24, W - margin + 14, H - 24], outline=ink, width=2)

    block(brand, _load_font(True, 44), 14)
    block(class_type, _load_font(False, 25), 20)
    block(alcohol, _load_font(True, 25), 10)
    block(net, _load_font(True, 25), 26)
    block(bottler_name, _load_font(False, 21), 6)
    block(bottler_address, _load_font(False, 21), 18)
    if country:
        block(country, _load_font(True, 22), 18)

    # Warning block pinned near the bottom, bold.
    warn_font = _load_font(True, 19)
    lines = _wrap(d, warning, warn_font, W - 2 * margin)
    warn_top = H - 64 - sum(warn_font.size + 9 for _ in lines)
    y = max(y, warn_top)
    for line in lines:
        d.text((margin, y), line, font=warn_font, fill=ink)
        y += warn_font.size + 9

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def make_imperfect(src: Path, dst: Path) -> None:
    """Bonus scenario: a photo of the label taken at a slight angle with glare."""
    img = Image.open(src).convert("RGB")

    # Slight rotation with dark desk background (a photo, not flat artwork).
    img = img.rotate(3.2, expand=True, fillcolor=(38, 40, 46))

    # Perspective-ish squeeze: resize non-uniformly then back.
    w, h = img.size
    img = img.resize((int(w * 1.06), int(h * 0.97))).resize((w, h))

    # Glare: a soft bright diagonal streak.
    glare = Image.new("L", img.size, 0)
    gd = ImageDraw.Draw(glare)
    for i in range(h):
        x_center = w * 0.62 + i * 0.12
        gd.line([(x_center - 60, i), (x_center + 60, i)], fill=90, width=1)
    glare = glare.filter(ImageFilter.GaussianBlur(38))
    white = Image.new("RGB", img.size, (255, 255, 255))
    img = Image.composite(white, img, glare)

    # Dim lighting + sensor noise + slight defocus.
    img = Image.eval(img, lambda p: max(0, int(p * 0.82)))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    rnd = random.Random(7)
    noise = Image.effect_noise(img.size, 18).convert("L")
    img = Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.06)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)


WARNING_2ND_SENTENCE_ALT = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause serious health problems."
)
WARNING_TYPO = CANONICAL_WARNING.replace("Surgeon General", "Surgeon Genral")
WARNING_MIXED_CASE_HEADER = "Government Warning:" + CANONICAL_WARNING[len("GOVERNMENT WARNING:"):]

BOURBON_APP = {
    "application_id": "TTB-2026-0001",
    "brand_name": "OLD TOM DISTILLERY",
    "class/type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_pct": 45.0,
    "net_contents_ml": 750,
    "bottler_name": "Old Tom Distillery Co.",
    "bottler_address": "123 Barrel Lane, Frankfort, KY 40601",
    "is_import": False,
    "country_of_origin": None,
}

WINE_APP = {
    "application_id": "TTB-2026-0002",
    "brand_name": "STONE'S THROW",
    "class/type": "Red Wine",
    "alcohol_pct": 13.5,
    "net_contents_ml": 750,
    "bottler_name": "Vintners Hall Imports",
    "bottler_address": "500 Harbor Blvd, Newark, NJ 07114",
    "is_import": True,
    "country_of_origin": "France",
}

# (name, title, application dict, printed label overrides, expected overall)
SCENARIOS = [
    (
        "bourbon_ok",
        "Bourbon: label matches application (all OK)",
        BOURBON_APP,
        {},
        "match",
    ),
    (
        "bourbon_case",
        "Bourbon: brand printed in different case (should still pass)",
        {**BOURBON_APP, "application_id": "TTB-2026-0011"},
        {"brand": "old tom DISTILLERY"},
        "match",
    ),
    (
        "bourbon_abv_wrong",
        "Bourbon: label says 43% but application says 45%",
        {**BOURBON_APP, "application_id": "TTB-2026-0012"},
        {"alcohol": "43% ALC./VOL. (86 PROOF)"},
        "mismatch",
    ),
    (
        "bourbon_warning_typo",
        "Bourbon: one letter off in the warning (needs a human look)",
        {**BOURBON_APP, "application_id": "TTB-2026-0013"},
        {"warning": WARNING_TYPO},
        "review",
    ),
    (
        "bourbon_warning_header",
        "Bourbon: warning header not in all caps (fails)",
        {**BOURBON_APP, "application_id": "TTB-2026-0015"},
        {"warning": WARNING_MIXED_CASE_HEADER},
        "mismatch",
    ),
    (
        "bourbon_warning_wrong",
        "Bourbon: warning wording changed (fails)",
        {**BOURBON_APP, "application_id": "TTB-2026-0014"},
        {"warning": WARNING_2ND_SENTENCE_ALT},
        "mismatch",
    ),
    (
        "wine_import",
        "Imported wine: includes country of origin (all OK)",
        WINE_APP,
        {},
        "match",
    ),
    (
        "wine_net_wrong",
        "Imported wine: label says 500 mL but application says 750 mL",
        {**WINE_APP, "application_id": "TTB-2026-0022"},
        {"net": "500 mL"},
        "mismatch",
    ),
]


def default_printed(app: dict) -> dict:
    return {
        "brand": app["brand_name"],
        "class_type": app["class/type"],
        "alcohol": f"{app['alcohol_pct']:g}% ALC./VOL. ({app['alcohol_pct'] * 2:g} PROOF)",
        "net": f"{app['net_contents_ml']:g} mL",
        "bottler_name": f"Bottled by {app['bottler_name']}",
        "bottler_address": app["bottler_address"],
        "country": f"Product of {app['country_of_origin']}" if app["is_import"] else None,
        "warning": CANONICAL_WARNING,
    }


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    index = []

    for name, title, app, overrides, expected in SCENARIOS:
        printed = {**default_printed(app), **overrides}
        draw_label(SAMPLES_DIR / f"{name}.png", **printed)
        index.append({"name": name, "title": title, "application": app, "expected": expected})

    # Bonus: imperfect photo of the OK bourbon label.
    make_imperfect(SAMPLES_DIR / "bourbon_ok.png", SAMPLES_DIR / "imperfect_photo.png")
    index.insert(1, {
        "name": "imperfect_photo",
        "title": "Bourbon: photo taken at an angle with glare (bonus test)",
        "application": BOURBON_APP,
        "expected": "bonus",
    })

    (SAMPLES_DIR / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Batch demo CSV references the images by filename.
    with open(SAMPLES_DIR / "applications.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "application_id", "image_filename", "brand_name", "class_type",
            "alcohol_pct", "net_contents_ml", "bottler_name", "bottler_address",
            "is_import", "country_of_origin",
        ])
        for item in index:
            app = item["application"]
            writer.writerow([
                app["application_id"], f"{item['name']}.png", app["brand_name"],
                app["class/type"], app["alcohol_pct"], app["net_contents_ml"],
                app["bottler_name"], app["bottler_address"],
                str(app["is_import"]).lower(), app["country_of_origin"] or "",
            ])

    print(f"Wrote {len(index)} sample labels to {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
