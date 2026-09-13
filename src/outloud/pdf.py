"""PDF text extraction with PyMuPDF. Scanned pages (no text layer) are detected so the
app can fall back to OCR on a rendered image of the page."""
from __future__ import annotations

from typing import List

try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF releases
    import fitz  # type: ignore

MIN_TEXT_CHARS = 20


class PdfDocument:
    def __init__(self, path: str) -> None:
        self.path = path
        self.doc = fitz.open(path)

    @property
    def page_count(self) -> int:
        return len(self.doc)

    def page_text(self, index: int) -> str:
        """Text of one page, blocks in reading order, paragraphs separated by blank lines."""
        page = self.doc[index]
        blocks = page.get_text("blocks", sort=True)
        parts = [b[4].strip() for b in blocks if len(b) < 7 or b[6] == 0]
        return "\n\n".join(p for p in parts if p)

    def looks_scanned(self, index: int) -> bool:
        return len(self.page_text(index).strip()) < MIN_TEXT_CHARS

    def render(self, index: int, zoom: float = 2.0):
        """Render a page to a PIL image (for OCR)."""
        from PIL import Image

        pix = self.doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        mode = "RGBA" if pix.alpha else "RGB"
        return Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")

    def all_text(self) -> List[str]:
        return [self.page_text(i) for i in range(self.page_count)]

    def close(self) -> None:
        self.doc.close()
