import pytest
from PIL import Image, ImageDraw, ImageFont

from outloud import ocr
from outloud.ocr import OcrLine


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
def test_ocr_reads_rendered_text_with_boxes():
    img = _text_image("The quick brown fox jumps.")
    lines = ocr.recognize_lines(img)
    if lines is None:
        pytest.skip("text-only OCR engine")
    texts = [l.text.lower() for l in lines]
    assert any("quick brown fox" in t for t in texts)
    first = next(l for l in lines if "quick" in l.text.lower())
    second = next(l for l in lines if "second" in l.text.lower())
    assert 0 <= first.y0 < first.y1 <= 1 and first.y1 <= second.y0 + 0.05  # first line sits above the second
    assert first.x0 < 0.1  # both start near the left edge
    out = ocr.recognize(img).lower()
    assert out.index("quick") < out.index("second")


def test_layout_orders_rows_and_paragraphs():
    lines = [
        OcrLine("right of top", 0.5, 0.08, 0.9, 0.12),
        OcrLine("top", 0.1, 0.07, 0.3, 0.11),
        OcrLine("far below", 0.1, 0.50, 0.4, 0.54),
    ]
    laid = ocr.layout_lines(lines)
    assert [t[2] for t in laid] == ["top", "right of top", "far below"]
    assert [t[0] for t in laid] == [0, 0, 1]
    assert ocr.lines_to_text(lines) == "top right of top\n\nfar below"


def test_recognize_raises_help_when_nothing_available(monkeypatch):
    monkeypatch.setattr(ocr, "LINE_ENGINES", [])
    monkeypatch.setattr(ocr, "_tesseract_text", lambda img: (_ for _ in ()).throw(ocr.OCRUnavailable("no")))
    with pytest.raises(ocr.OCRUnavailable):
        ocr.recognize(Image.new("RGB", (10, 10)))
