"""A continuous-scroll PDF viewer widget (Qt) that can highlight boxes on pages.

Pages are laid out top to bottom, fit to the width of the view (zoom 1.0), and
rendered by PyMuPDF only when they come into view, at the screen's real pixel
density so text is crisp on Retina displays. Highlights are drawn with a
multiply blend, so they look like a highlighter pen over the print.
"""
from __future__ import annotations

import sys
from bisect import bisect_right
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea

from .pdf import PdfDocument, Rect

BACKGROUND = QColor(82, 86, 89)
HIGHLIGHT = QColor(255, 232, 92)


class PdfViewer(QAbstractScrollArea):
    currentPageChanged = Signal(int)  # 0-based
    clicked = Signal(int, float, float)  # page, x, y in page points

    MARGIN = 18
    SPACING = 14
    CACHE_PAGES = 24

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.doc: Optional[PdfDocument] = None
        self.sizes: List[Tuple[float, float]] = []
        self.scale: List[float] = []
        self.heights: List[float] = []
        self.offsets: List[float] = []
        self.page_w = 0.0
        self.doc_w = 0.0
        self.doc_h = 0.0
        self.zoom = 1.0
        self.cache: "OrderedDict[int, QPixmap]" = OrderedDict()
        self.highlights: Dict[int, List[Rect]] = {}
        self.current_page = 0
        mod = "⌘" if sys.platform == "darwin" else "Ctrl+"
        self.hint = f"Open a PDF ({mod}O) or drop one here.\n\nFor anything else on your screen, use “Read from screen”."

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._render_pending)

    # ------------------------------------------------------------ document
    def set_document(self, doc: Optional[PdfDocument]) -> None:
        self.doc = doc
        self.sizes = doc.page_sizes() if doc else []
        self.cache.clear()
        self.highlights = {}
        self.zoom = 1.0
        self.current_page = 0
        self._relayout()
        self.verticalScrollBar().setValue(0)
        self.horizontalScrollBar().setValue(0)
        self.currentPageChanged.emit(0)
        self.viewport().update()

    @property
    def page_count(self) -> int:
        return len(self.sizes)

    # -------------------------------------------------------------- layout
    def _relayout(self) -> None:
        vw = self.viewport().width()
        vh = self.viewport().height()
        vsb, hsb = self.verticalScrollBar(), self.horizontalScrollBar()
        if not self.sizes:
            self.doc_h = self.doc_w = self.page_w = 0.0
            self.offsets, self.heights, self.scale = [], [], []
            vsb.setRange(0, 0)
            hsb.setRange(0, 0)
            return
        self.page_w = max(80.0, (vw - 2 * self.MARGIN) * self.zoom)
        self.scale = [self.page_w / max(1.0, w) for w, _h in self.sizes]
        self.heights = [h * s for (_w, h), s in zip(self.sizes, self.scale)]
        y = float(self.MARGIN)
        self.offsets = []
        for h in self.heights:
            self.offsets.append(y)
            y += h + self.SPACING
        self.doc_h = y - self.SPACING + self.MARGIN
        self.doc_w = self.page_w + 2 * self.MARGIN
        vsb.setRange(0, max(0, int(self.doc_h - vh)))
        vsb.setPageStep(max(1, int(vh * 0.9)))
        vsb.setSingleStep(40)
        hsb.setRange(0, max(0, int(self.doc_w - vw)))
        hsb.setPageStep(max(1, vw))
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn if self.doc_w > vw + 1 else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.cache.clear()

    def _page_at_y(self, y: float) -> int:
        if not self.offsets:
            return 0
        i = bisect_right(self.offsets, y) - 1
        return max(0, min(i, len(self.offsets) - 1))

    def _page_x(self, index: int) -> float:
        return (max(self.viewport().width(), self.doc_w) - self.page_w) / 2

    def _anchor(self) -> Optional[Tuple[int, float]]:
        if not self.offsets:
            return None
        sy = self.verticalScrollBar().value()
        i = self._page_at_y(sy + 1)
        return i, (sy - self.offsets[i]) / max(1.0, self.heights[i])

    def _restore(self, anchor: Optional[Tuple[int, float]]) -> None:
        if anchor is None or not self.offsets:
            return
        i, frac = anchor
        i = min(i, len(self.offsets) - 1)
        self.verticalScrollBar().setValue(int(self.offsets[i] + frac * self.heights[i]))

    def resizeEvent(self, event) -> None:
        anchor = self._anchor()
        self._relayout()
        self._restore(anchor)
        super().resizeEvent(event)

    # ---------------------------------------------------------- navigation
    def goto_page(self, index: int) -> None:
        if not self.offsets:
            return
        index = max(0, min(index, len(self.offsets) - 1))
        self.verticalScrollBar().setValue(int(self.offsets[index] - self.MARGIN / 2))
        self._scrolled(self.verticalScrollBar().value())

    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.5, min(4.0, zoom))
        if abs(zoom - self.zoom) < 1e-6:
            return
        anchor = self._anchor()
        self.zoom = zoom
        self._relayout()
        self._restore(anchor)
        self.viewport().update()

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom / 1.2)

    def fit_width(self) -> None:
        self.set_zoom(1.0)

    def _scrolled(self, value: int) -> None:
        if self.offsets:
            page = self._page_at_y(value + self.viewport().height() * 0.35)
            if page != self.current_page:
                self.current_page = page
                self.currentPageChanged.emit(page)
        self.viewport().update()

    # ---------------------------------------------------------- highlights
    def set_highlight(self, page: int, rects: List[Rect]) -> None:
        self.highlights = {page: list(rects)} if rects else {}
        if rects and self.offsets and 0 <= page < len(self.offsets):
            s = self.scale[page]
            top = self.offsets[page] + min(r[1] for r in rects) * s
            bottom = self.offsets[page] + max(r[3] for r in rects) * s
            vsb = self.verticalScrollBar()
            sy, vh = vsb.value(), self.viewport().height()
            if top < sy + 8 or bottom > sy + vh - 8:
                vsb.setValue(int(top - vh * 0.3))
        self.viewport().update()

    def clear_highlight(self) -> None:
        self.highlights = {}
        self.viewport().update()

    # ------------------------------------------------------------ painting
    def _visible_pages(self) -> Tuple[int, int]:
        sy = self.verticalScrollBar().value()
        return self._page_at_y(sy), self._page_at_y(sy + self.viewport().height())

    def paintEvent(self, event) -> None:
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), BACKGROUND)
        if not self.sizes:
            p.setPen(QPen(QColor(230, 230, 230)))
            f = QFont()
            f.setPointSize(16)
            p.setFont(f)
            p.drawText(self.viewport().rect().adjusted(40, 0, -40, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.hint)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        sx, sy = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        first, last = self._visible_pages()
        pending = False
        for i in range(first, last + 1):
            x = self._page_x(i) - sx
            y = self.offsets[i] - sy
            w, h = self.page_w, self.heights[i]
            page_rect = QRectF(x, y, w, h)
            p.fillRect(page_rect.translated(2, 3), QColor(0, 0, 0, 70))
            pm = self.cache.get(i)
            if pm is not None:
                p.drawPixmap(page_rect, pm, QRectF(pm.rect()))
            else:
                p.fillRect(page_rect, Qt.GlobalColor.white)
                pending = True
            rects = self.highlights.get(i)
            if rects:
                s = self.scale[i]
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
                for x0, y0, x1, y1 in rects:
                    r = QRectF(x + x0 * s, y + y0 * s, (x1 - x0) * s, (y1 - y0) * s).adjusted(-3, -2, 3, 2)
                    p.fillRect(r, HIGHLIGHT)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if pending and not self._timer.isActive():
            self._timer.start()

    def _render_pending(self) -> None:
        if not self.doc or not self.sizes:
            return
        first, last = self._visible_pages()
        centre = (first + last) / 2
        todo = sorted((i for i in range(first, last + 1) if i not in self.cache), key=lambda i: abs(i - centre))
        for i in todo[:2]:
            self._render(i)
        self.viewport().update()
        if len(todo) > 2:
            self._timer.start()

    def _render(self, index: int) -> None:
        dpr = self.devicePixelRatioF()
        w, h, stride, data = self.doc.render_rgb(index, self.scale[index] * dpr)
        img = QImage(data, w, h, stride, QImage.Format.Format_RGB888).copy()
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        self.cache[index] = pm
        while len(self.cache) > self.CACHE_PAGES:
            self.cache.popitem(last=False)

    # --------------------------------------------------------------- input
    def page_point_at(self, pos: QPointF) -> Optional[Tuple[int, float, float]]:
        if not self.sizes:
            return None
        sx, sy = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        i = self._page_at_y(pos.y() + sy)
        px = (pos.x() + sx - self._page_x(i)) / self.scale[i]
        py = (pos.y() + sy - self.offsets[i]) / self.scale[i]
        w, h = self.sizes[i]
        if 0 <= px <= w and 0 <= py <= h:
            return i, px, py
        return None

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self.page_point_at(event.position())
            if hit is not None:
                self.clicked.emit(*hit)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        vsb = self.verticalScrollBar()
        key = event.key()
        if key == Qt.Key.Key_Home:
            vsb.setValue(0)
        elif key == Qt.Key.Key_End:
            vsb.setValue(vsb.maximum())
        else:
            super().keyPressEvent(event)
