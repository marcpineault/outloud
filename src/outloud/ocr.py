"""Optical character recognition for screen captures and scanned PDF pages.

Engines are tried in order; the first one present wins:

* macOS   -> Apple Vision (built in, excellent, no download)
* Windows -> Windows.Media.Ocr through the ``winocr`` package (built into Windows 10/11)
* any     -> RapidOCR (pip install rapidocr-onnxruntime) if installed
* any     -> Tesseract (pip install pytesseract + the tesseract binary), text only

The first three return lines WITH their boxes (0..1 of the image, origin top-left),
which lets the viewer highlight OCR'd text on the page just like real PDF text.
"""
from __future__ import annotations

import io
import shutil
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

HELP = (
    "No OCR engine is available on this computer.\n\n"
    "macOS: it is built in (Apple Vision). Reinstall with: pip install pyobjc-framework-Vision\n"
    "Windows: pip install winocr   (uses the OCR built into Windows 10/11)\n"
    "Any OS:  pip install rapidocr-onnxruntime"
)


class OCRUnavailable(RuntimeError):
    pass


@dataclass
class OcrLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


def _prepare(image):
    """Grayscale and upscale small captures; every engine reads them better that way."""
    img = image.convert("L") if image.mode not in ("L", "RGB") else image
    if img.width < 1400:
        img = img.resize((img.width * 2, img.height * 2))
    return img


# ----------------------------------------------------------------- engines
def _mac_vision(image) -> List[OcrLine]:
    if sys.platform != "darwin":
        raise OCRUnavailable("not macOS")
    try:
        import Quartz
        import Vision
        from Foundation import NSData
    except ImportError as exc:
        raise OCRUnavailable(f"Apple Vision bindings missing: {exc}")

    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    png = buf.getvalue()
    data = NSData.dataWithBytes_length_(png, len(png))
    source = Quartz.CGImageSourceCreateWithData(data, None)
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Apple Vision could not read the image: {error}")

    lines: List[OcrLine] = []
    for obs in request.results() or []:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        box = obs.boundingBox()  # normalized, origin bottom-left
        x0 = box.origin.x
        x1 = x0 + box.size.width
        y1 = 1.0 - box.origin.y
        y0 = y1 - box.size.height
        lines.append(OcrLine(candidates[0].string(), x0, y0, x1, y1))
    return lines


def _windows_native(image) -> List[OcrLine]:
    if sys.platform != "win32":
        raise OCRUnavailable("not Windows")
    try:
        import asyncio

        import winocr
    except ImportError as exc:
        raise OCRUnavailable(f"winocr missing: {exc}")
    rgb = image.convert("RGB")
    W, H = rgb.size

    async def _run():
        # Older winocr returns a coroutine, newer winrt builds return an awaitable
        # IAsyncOperation; awaiting inside a coroutine handles both.
        return await winocr.recognize_pil(rgb, "en")

    result = asyncio.run(_run())
    lines: List[OcrLine] = []
    for line in getattr(result, "lines", None) or []:
        words = list(getattr(line, "words", None) or [])
        text = getattr(line, "text", None) or " ".join(getattr(w, "text", "") for w in words)
        rects = [getattr(w, "bounding_rect", None) for w in words]
        rects = [r for r in rects if r is not None]
        if rects:
            x0 = min(r.x for r in rects) / W
            y0 = min(r.y for r in rects) / H
            x1 = max(r.x + r.width for r in rects) / W
            y1 = max(r.y + r.height for r in rects) / H
        else:
            x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
        if text.strip():
            lines.append(OcrLine(text, x0, y0, x1, y1))
    return lines


def _rapidocr(image) -> List[OcrLine]:
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise OCRUnavailable(f"rapidocr missing: {exc}")
    rgb = image.convert("RGB")
    W, H = rgb.size
    result, _ = RapidOCR()(np.array(rgb))
    lines: List[OcrLine] = []
    for box, text, _conf in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        lines.append(OcrLine(text, min(xs) / W, min(ys) / H, max(xs) / W, max(ys) / H))
    return lines


def _tesseract_text(image) -> str:
    try:
        import pytesseract
    except ImportError as exc:
        raise OCRUnavailable(f"pytesseract missing: {exc}")
    if not shutil.which("tesseract"):
        raise OCRUnavailable("tesseract binary not on PATH")
    return pytesseract.image_to_string(image)


LINE_ENGINES: List[Callable] = [_mac_vision, _windows_native, _rapidocr]


# ----------------------------------------------------------------- layout
def layout_lines(lines: List[OcrLine]) -> List[Tuple[int, int, str, float, float, float, float]]:
    """Order OCR lines for reading and tag each with (paragraph, row).

    Rows are lines sharing a vertical band (two columns become one row read
    left to right); a vertical gap larger than 1.8 line heights starts a new paragraph.
    Returns (block, line, text, x0, y0, x1, y1) tuples in reading order.
    """
    if not lines:
        return []
    median_h = sorted(l.h for l in lines)[len(lines) // 2] or 0.01
    ordered = sorted(lines, key=lambda l: (l.yc, l.x0))
    rows: List[Tuple[float, List[OcrLine]]] = []
    for l in ordered:
        if rows and abs(rows[-1][0] - l.yc) < median_h * 0.5:
            rows[-1][1].append(l)
        else:
            rows.append((l.yc, [l]))
    out = []
    block = 0
    prev_yc: Optional[float] = None
    for row_no, (yc, ls) in enumerate(rows):
        if prev_yc is not None and (yc - prev_yc) > median_h * 1.8:
            block += 1
        for l in sorted(ls, key=lambda l: l.x0):
            out.append((block, row_no, l.text, l.x0, l.y0, l.x1, l.y1))
        prev_yc = yc
    return out


def lines_to_text(lines: List[OcrLine]) -> str:
    """Plain text: rows joined with spaces, paragraphs separated by a blank line."""
    paragraphs: List[List[str]] = []
    last_block = None
    last_row = None
    for block, row, text, *_ in layout_lines(lines):
        if block != last_block:
            paragraphs.append([])
            last_block = block
            last_row = None
        if last_row is not None and row != last_row:
            paragraphs[-1].append("\n")
        paragraphs[-1].append(text)
        last_row = row
    return "\n\n".join(" ".join(p).replace(" \n ", "\n") for p in paragraphs)


# ----------------------------------------------------------------- public
def available_backends() -> List[str]:
    names = []
    if sys.platform == "darwin":
        try:
            import Vision  # noqa: F401

            names.append("apple-vision")
        except ImportError:
            pass
    if sys.platform == "win32":
        try:
            import winocr  # noqa: F401

            names.append("windows-ocr")
        except ImportError:
            pass
    try:
        import rapidocr_onnxruntime  # noqa: F401

        names.append("rapidocr")
    except ImportError:
        pass
    if shutil.which("tesseract"):
        try:
            import pytesseract  # noqa: F401

            names.append("tesseract")
        except ImportError:
            pass
    return names


def recognize_lines(image) -> Optional[List[OcrLine]]:
    """Lines with boxes, or None when only a text-only engine (Tesseract) exists."""
    img = _prepare(image)
    for engine in LINE_ENGINES:
        try:
            return engine(img)
        except OCRUnavailable:
            continue
    return None


def recognize(image) -> str:
    """Return the text in a PIL image, or raise OCRUnavailable with install help."""
    lines = recognize_lines(image)
    if lines is not None:
        return lines_to_text(lines)
    try:
        return _tesseract_text(_prepare(image))
    except OCRUnavailable:
        raise OCRUnavailable(HELP)
