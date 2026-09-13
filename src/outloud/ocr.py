"""Optical character recognition for screen captures and scanned PDF pages.

Backends are tried in order and the first one that works wins:

* macOS   -> Apple Vision (built in, excellent, no download)
* Windows -> Windows.Media.Ocr through the ``winocr`` package (built into Windows 10/11)
* any     -> RapidOCR (pip install rapidocr-onnxruntime) if installed
* any     -> Tesseract (pip install pytesseract + the tesseract binary) if installed
"""
from __future__ import annotations

import io
import shutil
import sys
from typing import Callable, List

HELP = (
    "No OCR engine is available on this computer.\n\n"
    "macOS: it is built in (Apple Vision). Reinstall with: pip install pyobjc-framework-Vision\n"
    "Windows: pip install winocr   (uses the OCR built into Windows 10/11)\n"
    "Any OS:  pip install rapidocr-onnxruntime"
)


class OCRUnavailable(RuntimeError):
    pass


def _prepare(image):
    """Grayscale and upscale small captures; every engine reads them better that way."""
    img = image.convert("L") if image.mode not in ("L", "RGB") else image
    if img.width < 1400:
        scale = 2
        img = img.resize((img.width * scale, img.height * scale))
    return img


def _mac_vision(image) -> str:
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

    items = []  # (x, y_mid, height, text)  Vision's origin is bottom-left, normalized 0..1
    for obs in request.results() or []:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        box = obs.boundingBox()
        items.append((box.origin.x, box.origin.y + box.size.height / 2, box.size.height, candidates[0].string()))
    return _lines_from_boxes(items)


def _lines_from_boxes(items: List[tuple]) -> str:
    """Group word/line boxes into rows top-to-bottom, left-to-right; blank line on big gaps."""
    if not items:
        return ""
    median_h = sorted(i[2] for i in items)[len(items) // 2] or 0.01
    items.sort(key=lambda i: (-i[1], i[0]))
    rows: List[list] = []
    for x, y, _h, text in items:
        if rows and abs(rows[-1][0] - y) < median_h * 0.5:
            rows[-1][1].append((x, text))
        else:
            rows.append([y, [(x, text)]])
    lines: List[str] = []
    prev_y = None
    for y, parts in rows:
        parts.sort()
        if prev_y is not None and (prev_y - y) > median_h * 1.8:
            lines.append("")
        lines.append(" ".join(t for _, t in parts))
        prev_y = y
    return "\n".join(lines)


def _windows_native(image) -> str:
    if sys.platform != "win32":
        raise OCRUnavailable("not Windows")
    try:
        import asyncio

        import winocr
    except ImportError as exc:
        raise OCRUnavailable(f"winocr missing: {exc}")
    rgb = image.convert("RGB")

    async def _run():
        # Older winocr returns a coroutine, newer winrt builds return an awaitable
        # IAsyncOperation; awaiting inside a coroutine handles both.
        return await winocr.recognize_pil(rgb, "en")

    result = asyncio.run(_run())
    lines = getattr(result, "lines", None)
    if lines:
        return "\n".join(getattr(line, "text", str(line)) for line in lines)
    return getattr(result, "text", "") or ""


def _rapidocr(image) -> str:
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise OCRUnavailable(f"rapidocr missing: {exc}")
    engine = RapidOCR()
    result, _ = engine(np.array(image.convert("RGB")))
    if not result:
        return ""
    items = []
    for box, text, _conf in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        h = max(ys) - min(ys)
        # flip y so "higher on the page" sorts first like the Vision path
        items.append((min(xs), -(min(ys) + h / 2), h, text))
    return _lines_from_boxes(items)


def _tesseract(image) -> str:
    try:
        import pytesseract
    except ImportError as exc:
        raise OCRUnavailable(f"pytesseract missing: {exc}")
    if not shutil.which("tesseract"):
        raise OCRUnavailable("tesseract binary not on PATH")
    return pytesseract.image_to_string(image)


BACKENDS: List[Callable] = [_mac_vision, _windows_native, _rapidocr, _tesseract]


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


def recognize(image) -> str:
    """Return the text in a PIL image, or raise OCRUnavailable with install help."""
    img = _prepare(image)
    for backend in BACKENDS:
        try:
            return backend(img)
        except OCRUnavailable:
            continue
    raise OCRUnavailable(HELP)
