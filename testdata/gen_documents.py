"""Render the fictional household documents for the proof-of-loss test archive.

Every household spec in testdata/spec has a "documents" list. Each entry is
written to testdata/archive/<household>/<path>:

- PDF kinds (order_confirmation, delivery_note, invoice, till_receipt, bill,
  policy, manual) are drawn with reportlab and carry real selectable text.
- till_receipt_photo entries are drawn with Pillow as a phone photo of a paper
  receipt, and get EXIF (capture time, camera make and model, home GPS) from
  piexif.

Output is deterministic: reportlab runs in invariant mode and every random
choice is seeded from the document id, so reruns give identical bytes.

Usage:
    python -I testdata/gen_documents.py           render all files, then check
    python -I testdata/gen_documents.py --check   run the acceptance checks only
"""

import datetime
import io
import json
import random
import sys
import zlib
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import piexif
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from pypdf import PdfReader
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

# No timestamps or random IDs in the PDFs, so reruns match byte for byte.
rl_config.invariant = 1

HERE = Path(__file__).resolve().parent
SPEC_DIR = HERE / "spec"
ARCHIVE_DIR = HERE / "archive"
HOUSEHOLDS = ("household_a", "household_b")
MAX_BYTES = 1_000_000

# Fictional merchant and insurer addresses (street, city line), keyed by the
# merchant name as written in the specs. A merchant always gets the same one.
ADDRESSES = {
    "Maison Electro": ("22 Cours des Peupliers", "69007 Lyon"),
    "Cyclonord": ("5 Rue Vallon-Clair", "69002 Lyon"),
    "PhotoQuai": ("41 Quai des Images", "69001 Lyon"),
    "Maison Lune": ("3 Place de la Lune", "69003 Lyon"),
    "Bijouterie Rocher": ("12 Rue du Rocher Bleu", "69002 Lyon"),
    "Electro Discount": ("88 Avenue des Forges", "69008 Lyon"),
    "SoundMart": ("7 Galerie Sonore", "69006 Lyon"),
    "Energie Rhone": ("1 Rue Ecluse Haute", "69003 Lyon"),
    "Fibra": ("9 Boulevard des Fibres", "69009 Lyon"),
    "Assurances Lumen": ("2 Place Lumen", "69002 Lyon"),
    "Veltra": ("1 Parc des Ateliers", "38000 Grenoble"),
    "Cafe Atelier": ("14 Rue des Meuniers", "59000 Lille"),
    "Nordtech": ("30 Rue du Haut Pre", "59000 Lille"),
    "Muziekhuis Arend": ("6 Lange Ster", "9000 Gent"),
    "Bureau Plus": ("8 Rue des Imprimeurs", "59000 Lille"),
    "Mutuelle du Nord": ("25 Rue de la Vieille Halle", "59800 Lille"),
}

# Policyholder for each household (used on the policy PDF).
PEOPLE = {
    "household_a": {"name": "Claire Varga", "address": ("18 Impasse des Gravillons", "69004 Lyon")},
    "household_b": {"name": "Jonas Peeters", "address": ("9 Allee des Lupins", "59000 Lille")},
}

# Make and model written into the EXIF of each household's receipt photos.
DEVICES = {
    "household_a": ("Pellam", "P7"),
    "household_b": ("Corvid", "C12"),
}

MANUAL_PRODUCT = "Veltra 55Q8 TV"

PDF_TITLES = {
    "order_confirmation": "Order confirmation",
    "delivery_note": "Delivery note",
    "invoice": "Invoice",
    "till_receipt": "Receipt",
    "bill": "Bill",
}

# Layout. The footer is 7 pt grey text at the bottom of the page.
FOOTER_SIZE = 7
FOOTER_LEADING = 9
FOOTER_BASE = 10 * mm
A4_MARGIN = 20 * mm
A4_BODY_W = A4[0] - 2 * A4_MARGIN
RECEIPT_WIDTH = 80 * mm
RECEIPT_SIDE = 6 * mm
RECEIPT_BODY_W = RECEIPT_WIDTH - 2 * RECEIPT_SIDE

# Receipt photo geometry. Text is never set below MIN_FONT_PX.
PHOTO_SIZE = (1280, 960)
PAPER_W = 600
PAPER_PAD = 28
PAPER_RGB = (246, 243, 232)
INK = (0, 0, 0, 255)
HEAD_PX, BODY_PX, TOTAL_PX = 32, 26, 28
MIN_FONT_PX = 22
ROW_HEIGHT = {"head": 48, "center": 42, "text": 42, "indent": 40, "rule": 28, "total": 48, "gap": 20}
CENTERED_ROWS = ("head", "center")
MONO_FONTS = {
    True: ["C:/Windows/Fonts/consolab.ttf", "C:/Windows/Fonts/courbd.ttf"],
    False: ["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf"],
}


# ---------------------------------------------------------------- helpers


def load_spec(key):
    """Read testdata/spec/<key>.json."""
    with open(SPEC_DIR / f"{key}.json", encoding="utf-8") as f:
        return json.load(f)


def archive_path(key, rel):
    """testdata/archive/<key>/<rel>. Refuses paths that leave the archive folder."""
    path = (ARCHIVE_DIR / key / rel).resolve()
    if not path.is_relative_to(ARCHIVE_DIR.resolve()):
        raise ValueError(f"path escapes the archive folder: {rel}")
    return path


def seed_for(doc_id):
    """Integer seed derived from a document id, so each file is always the same."""
    return zlib.crc32(doc_id.encode("utf-8"))


def fmt_date(iso):
    """'2021-11-15' -> '15/11/2021'."""
    return datetime.date.fromisoformat(iso).strftime("%d/%m/%Y")


def money(value):
    """Two decimals: '49.9' -> '49.90'."""
    return f"{Decimal(value):.2f}"


def fmt_total(doc):
    """'Total: 1348.90 EUR', without the currency when the spec has none."""
    parts = ["Total:", doc["total"]]
    if doc.get("currency"):
        parts.append(doc["currency"])
    return " ".join(parts)


def _squash(text):
    """Collapse runs of whitespace, so wrapped lines compare equal to the source."""
    return " ".join(text.split())


# ---------------------------------------------------------------- PDF pages


def _para(text, size=10, bold=False, grey=False, align=TA_LEFT):
    """A reportlab paragraph. `text` is markup, so escape user data first."""
    style = ParagraphStyle(
        "body",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=size * 1.45,
        alignment=align,
        textColor=colors.HexColor("#555555") if grey else colors.black,
    )
    return Paragraph(text, style)


def _footer_lines(footer, width):
    """Footer text wrapped to `width`, in 7 pt Helvetica. Empty when there is no footer."""
    if not footer:
        return []
    return simpleSplit(footer, "Helvetica", FOOTER_SIZE, width)


def _bottom_margin(footer_lines, minimum):
    """Bottom margin that leaves room for the footer block."""
    if not footer_lines:
        return minimum
    return max(minimum, FOOTER_BASE + len(footer_lines) * FOOTER_LEADING + 4 * mm)


def _draw_footer(footer_lines, left):
    """Return an onPage callback that prints the footer lines at the bottom."""

    def draw(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", FOOTER_SIZE)
        canvas.setFillColor(colors.grey)
        for i, line in enumerate(footer_lines):
            y = FOOTER_BASE + (len(footer_lines) - 1 - i) * FOOTER_LEADING
            canvas.drawString(left, y, line)
        canvas.restoreState()

    return draw


def _build_pdf(story, pagesize, margins, footer_lines, title):
    """Lay the story out on one page template, with the footer on every page.

    margins is (left, right, top, bottom) in points. The frame has no padding,
    so the width used for measuring matches the width used for layout.
    """
    left, right, top, bottom = margins
    page_w, page_h = pagesize
    frame = Frame(
        left,
        bottom,
        page_w - left - right,
        page_h - top - bottom,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    on_page = _draw_footer(footer_lines, left) if footer_lines else (lambda c, d: None)
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=pagesize, title=title)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])
    doc.build(story)
    return buf.getvalue()


def _a4_pdf(story, footer, title):
    lines = _footer_lines(footer, A4_BODY_W)
    bottom = _bottom_margin(lines, A4_MARGIN)
    return _build_pdf(story, A4, (A4_MARGIN, A4_MARGIN, A4_MARGIN, bottom), lines, title)


def _receipt_pdf(story, footer, title):
    """An 80 mm wide slip. The page height is measured from the story."""
    lines = _footer_lines(footer, RECEIPT_BODY_W)
    bottom = _bottom_margin(lines, RECEIPT_SIDE)
    body_h = sum(flowable.wrap(RECEIPT_BODY_W, 1e6)[1] for flowable in story)
    height = RECEIPT_SIDE + body_h + bottom + 2 * mm
    margins = (RECEIPT_SIDE, RECEIPT_SIDE, RECEIPT_SIDE, bottom)
    return _build_pdf(story, (RECEIPT_WIDTH, height), margins, lines, title)


def _line_table(doc, narrow, scale):
    """Description, Qty, Unit price, Amount. A serial is printed under its line."""
    qty_w, unit_w, amount_w = (9 * mm, 17 * mm, 17 * mm) if narrow else (16 * mm, 28 * mm, 28 * mm)
    body_w = RECEIPT_BODY_W if narrow else A4_BODY_W
    desc_w = body_w - qty_w - unit_w - amount_w
    serials = doc.get("serials", {})
    size = 10 * scale
    rows = [
        [
            _para("Description", size, bold=True),
            _para("Qty", size, bold=True, align=TA_RIGHT),
            _para("Unit price", size, bold=True, align=TA_RIGHT),
            _para("Amount", size, bold=True, align=TA_RIGHT),
        ]
    ]
    for desc, qty, unit in doc["lines"]:
        label = escape(desc)
        if desc in serials:
            label += f"<br/><font size='{8 * scale:.1f}' color='#444444'>Serial number: {escape(serials[desc])}</font>"
        unit_text = "" if unit is None else money(unit)
        amount_text = "" if unit is None else money(Decimal(unit) * qty)
        rows.append(
            [
                _para(label, size),
                _para(str(qty), size, align=TA_RIGHT),
                _para(unit_text, size, align=TA_RIGHT),
                _para(amount_text, size, align=TA_RIGHT),
            ]
        )
    table = Table(rows, colWidths=[desc_w, qty_w, unit_w, amount_w])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _key_value_table(rows):
    data = [[_para(escape(k), 10, bold=True), _para(escape(v), 10)] for k, v in rows]
    table = Table(data, colWidths=[40 * mm, A4_BODY_W - 40 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _clauses(items):
    """Lettered clauses with a short gap between them."""
    story = []
    for i, text in enumerate(items):
        story.append(_para(f"({chr(ord('a') + i)}) {escape(text)}", 10))
        story.append(Spacer(1, 4))
    return story


# ---------------------------------------------------------------- PDF kinds


def render_commercial(doc):
    """Order confirmation, delivery note, invoice, bill, or till receipt."""
    narrow = doc["kind"] == "till_receipt"
    scale = 0.8 if narrow else 1.0
    align = TA_CENTER if narrow else TA_LEFT
    street, city = ADDRESSES[doc["merchant"]]
    story = [
        _para(escape(doc["merchant"]), 16 * scale, bold=True, align=align),
        _para(escape(street), 9 * scale, grey=True, align=align),
        _para(escape(city), 9 * scale, grey=True, align=align),
        Spacer(1, 12 * scale),
        _para(PDF_TITLES[doc["kind"]], 14 * scale, bold=True, align=align),
        Spacer(1, 4 * scale),
    ]
    if doc.get("number"):
        story.append(_para(f"No. {escape(doc['number'])}", 10 * scale, align=align))
    story.append(_para(f"Date: {fmt_date(doc['date'])}", 10 * scale, align=align))
    story.append(Spacer(1, 10 * scale))
    if doc.get("lines"):
        story.append(_line_table(doc, narrow, scale))
        story.append(Spacer(1, 8 * scale))
    if doc.get("total"):
        story.append(_para(escape(fmt_total(doc)), 11 * scale, bold=True, align=align))
    if doc.get("delivery"):
        story.append(_para(f"Delivery date: {fmt_date(doc['delivery'])}", 10 * scale, align=align))
    if doc.get("tracking"):
        story.append(_para(f"Tracking: {escape(doc['tracking'])}", 10 * scale, align=align))
    if doc.get("warranty_end"):
        story.append(_para(f"Warranty until: {fmt_date(doc['warranty_end'])}", 10 * scale, align=align))

    footer = doc.get("footer", "")
    title = f"{PDF_TITLES[doc['kind']]} {doc.get('number', '')}".strip()
    if narrow:
        return _receipt_pdf(story, footer, title)
    return _a4_pdf(story, footer, title)


def render_policy(doc, key):
    """Two-page home insurance policy. Insurer is the merchant."""
    person = PEOPLE[key]
    street, city = ADDRESSES[doc["merchant"]]
    rows = [
        ("Policy number", doc["number"]),
        ("Start date", fmt_date(doc["date"])),
        ("Policyholder", person["name"]),
        ("Insured address", ", ".join(person["address"])),
    ]
    story = [
        _para(escape(doc["merchant"]), 18, bold=True),
        _para(escape(f"{street}, {city}"), 10, grey=True),
        Spacer(1, 14),
        _para("Home insurance policy", 15, bold=True),
        Spacer(1, 8),
        _key_value_table(rows),
        Spacer(1, 14),
        _para("1. Contents cover", 11, bold=True),
        _para("Your household contents are insured up to 40,000 EUR in total at the insured address.", 10),
        Spacer(1, 10),
        _para("2. Valuables", 11, bold=True),
        _para(
            "Valuables (jewellery, watches) are covered up to 3,000 EUR per item without a valuation certificate.", 10
        ),
        PageBreak(),
        _para("3. Theft and burglary", 11, bold=True),
        _para("Theft and burglary are covered when there is forced entry.", 10),
        Spacer(1, 10),
        _para("4. Making a claim", 11, bold=True),
    ]
    story += _clauses(
        [
            "Declare a theft to us within two working days of discovering it.",
            "File a police report and send us a copy.",
            "Provide proof of ownership and value for each item claimed: invoices, "
            "receipts, photos, warranty cards or bank statements.",
        ]
    )
    story += [
        Spacer(1, 10),
        _para("5. Water damage", 11, bold=True),
        _para("Water damage is covered. Declare it to us within five working days of discovering it.", 10),
    ]
    return _a4_pdf(story, doc.get("footer", ""), f"Home insurance policy {doc['number']}")


def render_manual(doc):
    """One-page quick start guide. No prices and no serial number."""
    street, city = ADDRESSES[doc["merchant"]]
    steps = [
        "Remove the packaging and the protective film from the screen. Keep the box for any future move.",
        "Place the TV on a stable stand, or fit the wall bracket as shown in the mounting guide.",
        "Connect the power cable to the back of the TV, then to a wall socket.",
        "Insert the two batteries into the remote control.",
        "Connect your devices to the HDMI and USB ports on the back of the TV.",
        "Press the power button on the remote control. The set-up wizard starts.",
        "Choose your language, country and Wi-Fi network, then follow the on-screen steps.",
        "When the wizard asks, check for a software update and let it install.",
    ]
    story = [
        _para(escape(doc["merchant"]), 12, bold=True),
        _para(escape(f"{street}, {city}"), 9, grey=True),
        Spacer(1, 16),
        _para("Quick start guide", 20, bold=True),
        _para(escape(MANUAL_PRODUCT), 12),
        _para(f"Edition date: {fmt_date(doc['date'])}", 9, grey=True),
        Spacer(1, 16),
    ]
    for i, step in enumerate(steps, 1):
        story.append(_para(f"{i}. {escape(step)}", 10))
        story.append(Spacer(1, 6))
    return _a4_pdf(story, doc.get("footer", ""), "Quick start guide")


# ---------------------------------------------------------------- receipt photo


def _font(size, bold=False):
    """Monospace font from C:/Windows/Fonts (consola.ttf, else cour.ttf)."""
    if size < MIN_FONT_PX:
        raise ValueError(f"font size {size} px is below the {MIN_FONT_PX} px minimum")
    for path in MONO_FONTS[bold] + MONO_FONTS[False]:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise FileNotFoundError("no monospace font found in C:/Windows/Fonts")


def _receipt_rows(doc):
    """Receipt content as (kind, left, right) rows, top to bottom."""
    street, city = ADDRESSES[doc["merchant"]]
    taken = datetime.datetime.fromisoformat(doc["taken"])
    serials = doc.get("serials", {})
    rows = [
        ("head", doc["merchant"], ""),
        ("center", street, ""),
        ("center", city, ""),
        ("gap", "", ""),
        ("text", f"No. {doc['number']}", ""),
        ("text", taken.strftime("%d/%m/%Y %H:%M"), ""),
        ("rule", "", ""),
    ]
    for desc, qty, unit in doc["lines"]:
        label = desc if qty == 1 else f"{qty} x {desc}"
        rows.append(("text", label, money(Decimal(unit) * qty)))
        if desc in serials:
            # Kestrel frames are labelled "Frame no.", everything else "S/N".
            prefix = "Frame no." if "Kestrel" in desc else "S/N"
            rows.append(("indent", f"{prefix} {serials[desc]}", ""))
    rows += [
        ("rule", "", ""),
        ("total", "TOTAL", f"{doc['total']} {doc['currency']}"),
        ("gap", "", ""),
        ("center", "Thank you", ""),
    ]
    return rows


def _receipt_paper(doc):
    """The paper slip as an RGBA image: black text on off-white paper."""
    fonts = {"head": _font(HEAD_PX, bold=True), "total": _font(TOTAL_PX, bold=True)}
    body = _font(BODY_PX)
    rows = _receipt_rows(doc)
    height = 2 * PAPER_PAD + sum(ROW_HEIGHT[kind] for kind, _, _ in rows)
    paper = Image.new("RGBA", (PAPER_W, height), PAPER_RGB + (255,))
    draw = ImageDraw.Draw(paper)
    inner = PAPER_W - 2 * PAPER_PAD
    y = PAPER_PAD
    for kind, left, right in rows:
        row_h = ROW_HEIGHT[kind]
        mid = y + row_h / 2
        font = fonts.get(kind, body)
        if kind == "rule":
            for x in range(PAPER_PAD, PAPER_W - PAPER_PAD, 14):
                draw.line([(x, mid), (x + 8, mid)], fill=INK, width=2)
        elif left:
            price_w = font.getlength(right) + 16 if right else 0
            if font.getlength(left) + price_w > inner:
                raise ValueError(f"receipt row too wide: {left!r} {right!r}")
            if kind in CENTERED_ROWS:
                x = (PAPER_W - font.getlength(left)) / 2
            elif kind == "indent":
                x = PAPER_PAD + 28
            else:
                x = PAPER_PAD
            draw.text((x, mid), left, font=font, fill=INK, anchor="lm")
            if right:
                draw.text((PAPER_W - PAPER_PAD, mid), right, font=font, fill=INK, anchor="rm")
        y += row_h
    return paper


def _shade(rgb, delta):
    return tuple(max(0, min(255, c + delta)) for c in rgb)


def _wood_background(rng):
    """Procedural wood: planks of varying brown, grain lines and seams."""
    w, h = PHOTO_SIZE
    base = (120, 80, 48)
    img = Image.new("RGB", (w, h), base)
    draw = ImageDraw.Draw(img)
    y = 0
    while y < h:
        plank = rng.randint(130, 200)
        draw.rectangle([0, y, w, y + plank], fill=_shade(base, rng.randint(-14, 14)))
        for _ in range(rng.randint(10, 18)):
            gy = y + rng.randint(0, plank)
            draw.line(
                [(0, gy), (w, gy + rng.randint(-8, 8))],
                fill=_shade(base, rng.randint(-40, 12)),
                width=rng.randint(1, 3),
            )
        draw.line([(0, y), (w, y)], fill=(48, 30, 18), width=4)
        y += plank
    return img.filter(ImageFilter.GaussianBlur(1.0))


def _add_noise(img, rng, sigma):
    """Mild gaussian noise: the same grey offset is added to each channel."""
    w, h = img.size
    grain = bytes(min(255, max(0, round(128 + rng.gauss(0, sigma)))) for _ in range(w * h))
    layer = Image.frombytes("L", (w, h), grain)
    layer = Image.merge("RGB", (layer, layer, layer))
    return ImageChops.add(img, layer, scale=1.0, offset=-128)


def _place_receipt(scene, paper, rng):
    """Turn the slip 2 to 5 degrees and lay it on the scene with a soft shadow."""
    angle = rng.uniform(2.0, 5.0) * rng.choice((-1.0, 1.0))
    turned = paper.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))
    x = (scene.width - turned.width) // 2 + rng.randint(-40, 40)
    y = (scene.height - turned.height) // 2 + rng.randint(-30, 30)
    shadow = Image.new("L", scene.size, 0)
    shadow.paste(turned.getchannel("A"), (x + 8, y + 12))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10)).point(lambda v: v * 6 // 10)
    scene.paste((20, 12, 6), (0, 0, scene.width, scene.height), shadow)
    scene.paste(turned.convert("RGB"), (x, y), turned.getchannel("A"))
    return scene


def _dms(value):
    """Degrees as EXIF rationals ((deg, 1), (min, 1), (sec, 10000)). Carries are exact."""
    total = round(abs(value) * 3600 * 10000)
    deg, rest = divmod(total, 3600 * 10000)
    minute, rest = divmod(rest, 60 * 10000)
    return ((deg, 1), (minute, 1), (rest, 10000))


def _dms_to_degrees(dms):
    (d, dd), (m, md), (s, sd) = dms
    return d / dd + m / md / 60 + s / sd / 3600


def _exif_bytes(doc, key, home_gps):
    make, model = DEVICES[key]
    taken = datetime.datetime.fromisoformat(doc["taken"]).strftime("%Y:%m:%d %H:%M:%S")
    taken = taken.encode("ascii")
    lat, lon = home_gps
    return piexif.dump(
        {
            "0th": {
                piexif.ImageIFD.Make: make.encode("ascii"),
                piexif.ImageIFD.Model: model.encode("ascii"),
            },
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: taken,
                piexif.ExifIFD.DateTimeDigitized: taken,
            },
            "GPS": {
                piexif.GPSIFD.GPSVersionID: (2, 2, 0, 0),
                piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
                piexif.GPSIFD.GPSLatitude: _dms(lat),
                piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
                piexif.GPSIFD.GPSLongitude: _dms(lon),
            },
            "1st": {},
            "thumbnail": None,
        }
    )


def render_receipt_photo(doc, spec, key):
    """A till receipt photographed on a wooden table, as a 1280x960 JPEG with EXIF."""
    rng = random.Random(seed_for(doc["id"]))
    scene = _wood_background(rng)
    scene = _place_receipt(scene, _receipt_paper(doc), rng)
    scene = _add_noise(scene, rng, sigma=2.5)
    scene = scene.filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    scene.save(buf, format="JPEG", quality=88, exif=_exif_bytes(doc, key, spec["home_gps"]))
    return buf.getvalue()


# ---------------------------------------------------------------- dispatch


def render_document(key, spec, doc):
    """Return the file bytes for one spec document."""
    kind = doc["kind"]
    if kind == "till_receipt_photo":
        return render_receipt_photo(doc, spec, key)
    if kind == "policy":
        return render_policy(doc, key)
    if kind == "manual":
        return render_manual(doc)
    if kind in PDF_TITLES:
        return render_commercial(doc)
    raise ValueError(f"unknown kind {kind!r} in {doc['id']}")


def render_all():
    for key in HOUSEHOLDS:
        spec = load_spec(key)
        for doc in spec["documents"]:
            out = archive_path(key, doc["path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(render_document(key, spec, doc))
        print(f"{key}: wrote {len(spec['documents'])} files under {ARCHIVE_DIR / key}")


# ---------------------------------------------------------------- checks


def check_pdf(doc, path):
    """The PDF text must hold the merchant, number, lines, total, serials and footer."""
    failures = []
    reader = PdfReader(str(path))
    text = _squash(" ".join(page.extract_text() or "" for page in reader.pages))
    expected_pages = 2 if doc["kind"] == "policy" else 1
    if len(reader.pages) != expected_pages:
        failures.append(f"{len(reader.pages)} pages, expected {expected_pages}")
    expected = [doc["merchant"]]
    if doc.get("number"):
        expected.append(doc["number"])
    expected += [line[0] for line in doc.get("lines", [])]
    if doc.get("total"):
        expected.append(doc["total"])
    expected += list(doc.get("serials", {}).values())
    if doc.get("footer"):
        expected.append(doc["footer"])
    failures += [f"text missing: {s!r}" for s in expected if _squash(s) not in text]
    return failures


def _ref(value):
    return value.rstrip(b"\x00")


def check_photo(doc, key, spec, path):
    """Format and size, EXIF capture time, camera make and model, and home GPS."""
    failures = []
    with Image.open(path) as img:
        if img.format != "JPEG" or img.size != PHOTO_SIZE:
            failures.append(f"image is {img.format} {img.size}")
    exif = piexif.load(str(path))

    expected_time = datetime.datetime.fromisoformat(doc["taken"]).strftime("%Y:%m:%d %H:%M:%S")
    got_time = _ref(exif["Exif"].get(piexif.ExifIFD.DateTimeOriginal, b""))
    if got_time != expected_time.encode("ascii"):
        failures.append(f"DateTimeOriginal {got_time!r} != {expected_time!r}")

    make, model = DEVICES[key]
    if _ref(exif["0th"].get(piexif.ImageIFD.Make, b"")) != make.encode("ascii"):
        failures.append("Make mismatch")
    if _ref(exif["0th"].get(piexif.ImageIFD.Model, b"")) != model.encode("ascii"):
        failures.append("Model mismatch")

    gps = exif["GPS"]
    tags = (
        piexif.GPSIFD.GPSLatitudeRef,
        piexif.GPSIFD.GPSLatitude,
        piexif.GPSIFD.GPSLongitudeRef,
        piexif.GPSIFD.GPSLongitude,
    )
    if not all(tag in gps for tag in tags):
        failures.append("GPS tags missing")
    else:
        lat = _dms_to_degrees(gps[piexif.GPSIFD.GPSLatitude])
        lon = _dms_to_degrees(gps[piexif.GPSIFD.GPSLongitude])
        if _ref(gps[piexif.GPSIFD.GPSLatitudeRef]) == b"S":
            lat = -lat
        if _ref(gps[piexif.GPSIFD.GPSLongitudeRef]) == b"W":
            lon = -lon
        home_lat, home_lon = spec["home_gps"]
        if abs(lat - home_lat) > 1e-4 or abs(lon - home_lon) > 1e-4:
            failures.append(f"GPS {lat:.4f},{lon:.4f} differs from home_gps")
    return failures


def check_document(key, spec, doc, path):
    """Failure messages for one document. An empty list means it passes."""
    if not path.is_file():
        return ["file not written"]
    failures = []
    if path.stat().st_size >= MAX_BYTES:
        failures.append("1 MB or larger")
    if doc["kind"] == "till_receipt_photo":
        if path.suffix.lower() != ".jpg":
            return failures + ["photo path must end in .jpg"]
        return failures + check_photo(doc, key, spec, path)
    if path.suffix.lower() != ".pdf":
        return failures + ["document path must end in .pdf"]
    return failures + check_pdf(doc, path)


def run_checks():
    """Check every document in both specs. Prints one row each; returns the failure count."""
    results = []
    for key in HOUSEHOLDS:
        spec = load_spec(key)
        for doc in spec["documents"]:
            path = archive_path(key, doc["path"])
            failures = check_document(key, spec, doc, path)
            size_kb = f"{path.stat().st_size / 1024:.1f}" if path.is_file() else "-"
            result = "PASS" if not failures else "FAIL: " + "; ".join(failures)
            results.append((key, doc["id"], doc["path"], size_kb, result))

    print(f"{'household':<12}{'id':<17}{'path':<70}{'KB':>8}  check")
    for key, doc_id, rel, size_kb, result in results:
        print(f"{key:<12}{doc_id:<17}{rel:<70}{size_kb:>8}  {result}")
    failed = sum(1 for row in results if row[4] != "PASS")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return failed


def main(argv):
    if "--check" not in argv:
        render_all()
    return 1 if run_checks() else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
