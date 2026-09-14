"""PDF access with PyMuPDF: page sizes, rendering, and text with word boxes.

PyMuPDF is not thread-safe, so everything here is called from the GUI thread.
The viewer keeps that cheap by rendering only the pages on screen and caching.

``PageText`` is the bridge between speech and the picture of the page: it holds
the page's text, the sentence chunks cut from it, and for every token the box
it occupies on the page, so the sentence being read can be highlighted exactly
where it is printed and a click on the page can be turned into a sentence.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

if sys.platform == "win32":
    # On Windows, MuPDF loaded before Qt crashes the process with an access violation
    # (conflicting DLLs). Loading Qt first is harmless everywhere; see AGENTS.md.
    try:
        import PySide6.QtCore  # noqa: F401
    except ImportError:
        pass

try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF releases
    import fitz  # type: ignore

from .textsplit import Chunk, chunk_at, split_sentences

Rect = Tuple[float, float, float, float]  # x0, y0, x1, y1 in page points, origin top-left


@dataclass
class Token:
    text: str
    rect: Rect
    block: int
    line: int


class PageText:
    def __init__(self, tokens: List[Token], width: float, height: float, text: Optional[str] = None) -> None:
        self.width = width
        self.height = height
        self.tokens = tokens
        self.spans: List[Tuple[int, int]] = []
        if text is not None:  # OCR engine without boxes: text only, nothing to highlight
            self.text = text
        else:
            self.text = self._join(tokens)
        self.chunks: List[Chunk] = split_sentences(self.text)

    def _join(self, tokens: List[Token]) -> str:
        """Join tokens into text, deciding paragraph breaks from the print layout.

        PDFs are inconsistent about "blocks": some put a whole paragraph in one,
        others one per printed line. So a paragraph break is decided from
        geometry instead: a vertical step clearly larger than the usual line
        pitch, a jump back up the page (new column), or a change of type size
        (a heading next to body text). Same visual line -> space.
        """
        pitch = self._line_pitch(tokens)
        parts: List[str] = []
        pos = 0
        prev: Optional[Token] = None
        for tok in tokens:
            if prev is not None:
                sep = self._separator(prev, tok, pitch)
                if sep == "":
                    # a word hyphenated across lines: glue the halves, drop the hyphen
                    parts[-1] = parts[-1][:-1]
                    pos -= 1
                    self.spans[-1] = (self.spans[-1][0], pos)
                else:
                    parts.append(sep)
                    pos += len(sep)
            parts.append(tok.text)
            self.spans.append((pos, pos + len(tok.text)))
            pos += len(tok.text)
            prev = tok
        return "".join(parts)

    @staticmethod
    def _centre_height(tok: Token):
        x0, y0, x1, y1 = tok.rect
        return (y0 + y1) / 2, max(1.0, y1 - y0)

    @classmethod
    def _line_pitch(cls, tokens: List[Token]) -> float:
        """Typical distance between consecutive printed lines (lower quartile of the steps)."""
        steps = []
        for a, b in zip(tokens, tokens[1:]):
            yc_a, h_a = cls._centre_height(a)
            yc_b, _ = cls._centre_height(b)
            dy = yc_b - yc_a
            if dy > 0.5 * h_a:
                steps.append(dy)
        if not steps:
            return cls._centre_height(tokens[0])[1] * 1.3 if tokens else 14.0
        steps.sort()
        return steps[len(steps) // 4]

    @classmethod
    def _separator(cls, prev: Token, tok: Token, pitch: float) -> str:
        if prev.block == tok.block and prev.line == tok.line:
            return " "
        pyc, ph = cls._centre_height(prev)
        yc, h = cls._centre_height(tok)
        dy = yc - pyc
        if abs(dy) < 0.5 * min(h, ph):
            return " "  # same printed line, different block
        if dy < 0:
            return "\n"  # moved back up the page: a new column or a separate block
        if dy > 1.5 * pitch:
            return "\n"  # a blank line's worth of space: new paragraph
        if abs(h - ph) > 0.35 * max(h, ph):
            return "\n"  # heading next to body text
        if prev.text.endswith("-") and tok.text[:1].islower():
            return ""
        return " "

    @classmethod
    def from_ocr_lines(cls, laid_out: Iterable[Tuple[int, int, str, float, float, float, float]], width: float, height: float) -> "PageText":
        """From OCR lines laid out as (block, line, text, x0, y0, x1, y1) with 0..1 coordinates."""
        tokens = [
            Token(text, (x0 * width, y0 * height, x1 * width, y1 * height), block, line)
            for block, line, text, x0, y0, x1, y1 in laid_out
            if text.strip()
        ]
        return cls(tokens, width, height)

    def rects_for_chunk(self, index: int) -> List[Rect]:
        """One box per printed line covered by the chunk."""
        if not (0 <= index < len(self.chunks)):
            return []
        c = self.chunks[index]
        by_line = {}
        for tok, (s, e) in zip(self.tokens, self.spans):
            if e <= c.start or s >= c.end:
                continue
            key = (tok.block, tok.line)
            x0, y0, x1, y1 = tok.rect
            r = by_line.get(key)
            by_line[key] = (x0, y0, x1, y1) if r is None else (min(r[0], x0), min(r[1], y0), max(r[2], x1), max(r[3], y1))
        return list(by_line.values())

    def chunk_at_point(self, x: float, y: float, slack: float = 3.0) -> Optional[int]:
        """The chunk under a point on the page, or the nearest one on that printed line."""
        if not self.chunks:
            return None
        best: Optional[Tuple[float, int]] = None
        for tok, (s, _e) in zip(self.tokens, self.spans):
            x0, y0, x1, y1 = tok.rect
            if not (y0 - slack <= y <= y1 + slack):
                continue
            dx = 0.0 if x0 - slack <= x <= x1 + slack else min(abs(x - x0), abs(x - x1))
            if best is None or dx < best[0]:
                best = (dx, s)
        if best is None or best[0] > 60:
            return None
        return chunk_at(self.chunks, best[1])


class PdfDocument:
    def __init__(self, path: str) -> None:
        self.path = path
        self.doc = fitz.open(path)
        if self.doc.needs_pass:
            raise ValueError("This PDF is password protected.")

    @property
    def page_count(self) -> int:
        return len(self.doc)

    def page_size(self, index: int) -> Tuple[float, float]:
        r = self.doc[index].rect
        return float(r.width), float(r.height)

    def page_sizes(self) -> List[Tuple[float, float]]:
        return [self.page_size(i) for i in range(self.page_count)]

    def page_words(self, index: int) -> List[Token]:
        """Words in the PDF's natural (reading) order, boxes in displayed-page coordinates."""
        page = self.doc[index]
        matrix = page.rotation_matrix
        tokens: List[Token] = []
        for w in page.get_text("words"):
            text = w[4].strip()
            if not text:
                continue
            r = fitz.Rect(w[0], w[1], w[2], w[3]) * matrix
            r.normalize()
            tokens.append(Token(text, (r.x0, r.y0, r.x1, r.y1), int(w[5]), int(w[6])))
        return tokens

    def page_text_map(self, index: int) -> PageText:
        w, h = self.page_size(index)
        return PageText(self.page_words(index), w, h)

    def page_text(self, index: int) -> str:
        return self.page_text_map(index).text

    def looks_scanned(self, index: int) -> bool:
        """No usable text layer but there is a picture: probably a scan, worth OCR."""
        return len(self.page_words(index)) < 3 and bool(self.doc[index].get_images())

    def is_blank(self, index: int) -> bool:
        return not self.page_words(index) and not self.doc[index].get_images()

    def render(self, index: int, zoom: float = 2.0):
        """Render a page to a PIL image (for OCR)."""
        from PIL import Image

        pix = self.doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def render_rgb(self, index: int, scale: float) -> Tuple[int, int, int, bytes]:
        """Render for the viewer: (width, height, stride, RGB bytes)."""
        pix = self.doc[index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.width, pix.height, pix.stride, bytes(pix.samples)

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass
