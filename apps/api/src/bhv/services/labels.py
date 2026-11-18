"""Generate barcode Code 128 dan label siap cetak.

- Encoding Code 128 (pola modul) selalu dari python-barcode -> satu sumber untuk SVG & PDF.
  Encoder ini juga memakai charset C untuk deret angka sehingga barcode lebih pendek.
- PDF (reportlab) menggambar batang sebagai vektor dengan ukuran mm presisi.
- Printer thermal: lebar modul dibulatkan ke kelipatan TITIK printer (min. 2 titik). Kalau tidak
  muat, label DITOLAK (LabelTooSmall) daripada mencetak barcode yang sulit di-scan.
"""

import io
import math
from dataclasses import dataclass
from decimal import Decimal

from barcode import Code128 as PyCode128
from barcode.writer import SVGWriter
from reportlab.lib.units import mm as _mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

mm: float = _mm  # 1 mm dalam point PDF
MAX_LABELS_PER_JOB = 2000
QUIET_MODULES = 10  # quiet zone wajib Code 128 = 10 × lebar modul di tiap sisi
MIN_DOTS = 2  # 1 titik terlalu rapuh untuk scanner
_MAX_MODULE: float = 0.33 * mm
_MIN_MODULE_VECTOR: float = 0.19 * mm  # batas aman printer laser/inkjet


class LabelTooSmall(ValueError):
    def __init__(self, barcode: str, template: str) -> None:
        super().__init__(f"Barcode {barcode} tidak muat di template {template}")
        self.barcode = barcode
        self.template = template


def barcode_svg(value: str) -> bytes:
    buf = io.BytesIO()
    PyCode128(value, writer=SVGWriter()).write(
        buf,
        options={
            "module_width": 0.3,
            "module_height": 12.0,
            "quiet_zone": 3.0,
            "font_size": 9,
            "text_distance": 4.0,
            "background": "white",
            "foreground": "black",
        },
    )
    return buf.getvalue()


def module_pattern(value: str) -> str:
    """String '1'/'0' per modul (start + data + checksum + stop), tanpa quiet zone."""
    return str(PyCode128(value).build()[0])


@dataclass(frozen=True)
class Template:
    key: str
    title: str
    page_w: float
    page_h: float
    cols: int
    rows: int
    label_w: float
    label_h: float
    margin_left: float = 0
    margin_top: float = 0
    gap_x: float = 0
    gap_y: float = 0
    dpi: int | None = None  # None = printer laser/inkjet (vektor bebas); angka = thermal

    @property
    def per_page(self) -> int:
        return self.cols * self.rows

    @property
    def thermal(self) -> bool:
        return self.dpi is not None


TEMPLATES: dict[str, Template] = {
    t.key: t
    for t in [
        Template("a4_3x8", "A4 — 24 label (70 × 36 mm)", 210 * mm, 297 * mm, 3, 8,
                 70 * mm, 36 * mm, margin_top=4.5 * mm),
        Template("a4_4x10", "A4 — 40 label (48,5 × 25,4 mm)", 210 * mm, 297 * mm, 4, 10,
                 48.5 * mm, 25.4 * mm, margin_left=8 * mm, margin_top=21.5 * mm),
        Template("thermal_50x30", "Thermal 50 × 30 mm (printer 203 dpi)", 50 * mm, 30 * mm,
                 1, 1, 50 * mm, 30 * mm, dpi=203),
        Template("thermal_40x30", "Thermal 40 × 30 mm (printer 300 dpi)", 40 * mm, 30 * mm,
                 1, 1, 40 * mm, 30 * mm, dpi=300),
    ]
}  # fmt: skip


@dataclass(frozen=True)
class LabelData:
    barcode: str
    product_name: str
    size: str
    color: str | None
    price: Decimal | None


def _fit(text: str, font: str, size: float, max_w: float) -> str:
    if stringWidth(text, font, size) <= max_w:
        return text
    ell = "…"
    while text and stringWidth(text + ell, font, size) > max_w:
        text = text[:-1]
    return text.rstrip() + ell


def _rupiah(v: Decimal) -> str:
    return "Rp " + f"{int(v):,}".replace(",", ".")


def _dot(t: Template) -> float:
    assert t.dpi is not None
    return 25.4 / t.dpi * mm


def module_width(n_modules: int, avail_w: float, t: Template) -> float:
    """Lebar modul terbesar (≤ 0,33 mm) agar n_modules (+quiet zone) muat di avail_w."""
    total = n_modules + 2 * QUIET_MODULES
    x = min(avail_w / total, _MAX_MODULE)
    if t.thermal:
        dot = _dot(t)
        dots = math.floor(x / dot + 1e-9)
        if dots < MIN_DOTS:
            raise ValueError("too small")
        return dots * dot
    if x < _MIN_MODULE_VECTOR:
        raise ValueError("too small")
    return x


def _bar_area(t: Template) -> float:
    return t.label_w - 2 * mm  # 1 mm tepi; quiet zone sudah dihitung di modul


def check_fits(template_key: str, barcode: str) -> None:
    t = TEMPLATES[template_key]
    try:
        module_width(len(module_pattern(barcode)), _bar_area(t), t)
    except ValueError:
        raise LabelTooSmall(barcode, template_key) from None


def _draw_bars(c: Canvas, pattern: str, x0: float, y: float, module: float, height: float) -> None:
    i, n = 0, len(pattern)
    while i < n:
        if pattern[i] == "1":
            j = i
            while j < n and pattern[j] == "1":
                j += 1
            c.rect(x0 + i * module, y, (j - i) * module, height, stroke=0, fill=1)
            i = j
        else:
            i += 1


def _draw_label(c: Canvas, t: Template, x: float, y: float, d: LabelData, show_price: bool) -> None:
    pad = 2 * mm
    inner_w = t.label_w - 2 * pad
    top = y + t.label_h - pad
    small = t.label_h < 28 * mm

    name_size = 6.5 if small else 8
    c.setFont("Helvetica-Bold", name_size)
    name = _fit(d.product_name, "Helvetica-Bold", name_size, inner_w)
    c.drawString(x + pad, top - name_size, name)

    meta_size = 6 if small else 7
    meta = f"Ukuran {d.size}" + (f" · {d.color}" if d.color else "")
    price = _rupiah(d.price) if show_price and d.price is not None else ""
    c.setFont("Helvetica", meta_size)
    meta_y = top - name_size - meta_size - 1
    price_w = stringWidth(price, "Helvetica-Bold", meta_size) + (2 * mm if price else 0)
    c.drawString(x + pad, meta_y, _fit(meta, "Helvetica", meta_size, inner_w - price_w))
    if price:
        c.setFont("Helvetica-Bold", meta_size)
        c.drawRightString(x + t.label_w - pad, meta_y, price)

    text_size = 6.5 if small else 7.5
    text_y = y + pad
    bar_bottom = text_y + text_size + 1
    bar_h = max(meta_y - 2 - bar_bottom, 5 * mm)

    pattern = module_pattern(d.barcode)
    module = module_width(len(pattern), _bar_area(t), t)
    bars_w = len(pattern) * module
    bx = x + (t.label_w - bars_w) / 2
    if t.thermal:  # tepi batang tepat di grid titik printer
        dot = _dot(t)
        bx = round(bx / dot) * dot
    c.setFillColorRGB(0, 0, 0)
    _draw_bars(c, pattern, bx, bar_bottom, module, bar_h)

    c.setFont("Helvetica", text_size)
    c.drawCentredString(x + t.label_w / 2, text_y, d.barcode)


def render_labels_pdf(
    template_key: str, labels: list[LabelData], *, show_price: bool, start_position: int = 1
) -> bytes:
    t = TEMPLATES[template_key]
    for code in {lbl.barcode for lbl in labels}:
        check_fits(template_key, code)

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(t.page_w, t.page_h))
    c.setTitle("Label Barcode Bhavia")
    c.setAuthor("Bhavia International Tailor")

    slot = (start_position - 1) % t.per_page
    for i, d in enumerate(labels):
        if i > 0 and slot == 0:
            c.showPage()
        col, row = slot % t.cols, slot // t.cols
        x = t.margin_left + col * (t.label_w + t.gap_x)
        y = t.page_h - t.margin_top - (row + 1) * t.label_h - row * t.gap_y
        _draw_label(c, t, x, y, d, show_price)
        slot = (slot + 1) % t.per_page
    c.showPage()
    c.save()
    return buf.getvalue()
