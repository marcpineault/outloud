import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from outloud import ocr


def _text_image(text):
    img = Image.new("RGB", (900, 220), "white")
    draw = ImageDraw.Draw(img)
    font = None
    for path in ("/System/Library/Fonts/Helvetica.ttc", "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(path, 44)
            break
        except OSError:
            continue
    draw.text((30, 40), text, fill="black", font=font or ImageFont.load_default())
    draw.text((30, 120), "Second line here.", fill="black", font=font or ImageFont.load_default())
    return img


@pytest.mark.skipif(not ocr.available_backends(), reason="no OCR engine on this machine")
def test_ocr_reads_rendered_text():
    out = ocr.recognize(_text_image("The quick brown fox jumps."))
    low = out.lower()
    assert "quick brown fox" in low
    assert "second line" in low
    assert low.index("quick") < low.index("second")


def test_lines_from_boxes_orders_rows_and_paragraphs():
    items = [
        (0.5, 0.90, 0.04, "right of top"),
        (0.1, 0.91, 0.04, "top"),
        (0.1, 0.50, 0.04, "far below"),
    ]
    assert ocr._lines_from_boxes(items) == "top right of top\n\nfar below"


def test_recognize_raises_help_when_nothing_available(monkeypatch):
    monkeypatch.setattr(ocr, "BACKENDS", [])
    with pytest.raises(ocr.OCRUnavailable):
        ocr.recognize(Image.new("RGB", (10, 10)))
