"""Label hasil cetak benar-benar bisa di-scan.

PDF dirender pada resolusi printer sesungguhnya (thermal 203/300 dpi tanpa anti-aliasing, A4 300 dpi)
lalu didecode dengan zxing. Lebar batang thermal harus kelipatan titik printer, minimal 2 titik.
"""

from decimal import Decimal

import pypdfium2 as pdfium
import pytest
import zxingcpp

from bhv.services.labels import (
    MIN_DOTS,
    TEMPLATES,
    LabelData,
    LabelTooSmall,
    _bar_area,
    barcode_svg,
    check_fits,
    mm,
    module_pattern,
    module_width,
    render_labels_pdf,
)

NORMAL = LabelData(
    "BHV-0001-01",
    "Kemeja Batik Pria Lengan Panjang Motif Parang Premium Edisi Lebaran",
    "XXXL",
    "Merah Marun Tua",
    Decimal("1250000"),
)
OTHER = LabelData("BHV-9999-99", "Gamis Brokat", "M", None, None)
LONG = LabelData("BHV-12345-123", "Blazer", "L", None, None)  # >9999 barang, >99 varian


def _decode(pdf: bytes, template: str) -> list[str]:
    """Render per halaman pada dpi printer, lalu decode SETIAP sel label secara terpisah
    (seperti scanner membaca satu label). Sel kosong diabaikan."""
    t = TEMPLATES[template]
    dpi = t.dpi or 300
    px = dpi / 72  # pixel per point
    out: list[str] = []
    for page in pdfium.PdfDocument(pdf):
        img = page.render(scale=px, no_smoothpath=t.thermal).to_pil()
        for slot in range(t.per_page):
            col, row = slot % t.cols, slot // t.cols
            x = t.margin_left + col * (t.label_w + t.gap_x)
            top = t.margin_top + row * (t.label_h + t.gap_y)
            cell = img.crop((int(x * px), int(top * px),
                             int((x + t.label_w) * px), int((top + t.label_h) * px)))  # fmt: skip
            found = [r.text for r in zxingcpp.read_barcodes(cell)
                     if r.format == zxingcpp.BarcodeFormat.Code128]  # fmt: skip
            assert len(found) <= 1
            out += found
    return out


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_normal_codes_decode_at_printer_resolution(template: str) -> None:
    t = TEMPLATES[template]
    labels = [NORMAL, OTHER] * max(t.per_page // 2, 1)
    pdf = render_labels_pdf(template, labels, show_price=True)
    decoded = _decode(pdf, template)
    assert sorted(decoded) == sorted(lbl.barcode for lbl in labels)


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_thermal_modules_are_whole_dots(template: str) -> None:
    t = TEMPLATES[template]
    if not t.thermal:
        pytest.skip("hanya thermal")
    assert t.dpi
    dot = 25.4 / t.dpi * mm
    w = module_width(len(module_pattern(NORMAL.barcode)), _bar_area(t), t)
    assert round(w / dot, 6).is_integer() and w / dot >= MIN_DOTS


def test_long_code_rejected_where_it_cannot_be_scanned_reliably() -> None:
    with pytest.raises(LabelTooSmall):
        check_fits("thermal_50x30", LONG.barcode)  # butuh 49,5 mm dengan batang 2 titik
    for template in ("a4_3x8", "a4_4x10", "thermal_40x30"):
        check_fits(template, LONG.barcode)
        pdf = render_labels_pdf(template, [LONG], show_price=False)
        assert _decode(pdf, template) == [LONG.barcode]


def test_svg_preview_contains_code() -> None:
    svg = barcode_svg("BHV-0001-01")
    assert svg.startswith(b"<?xml") and b"BHV-0001-01" in svg
