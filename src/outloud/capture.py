"""Screen capture: a drag-to-select overlay plus screenshot helpers (Qt).

Coordinates are Qt's logical global coordinates. On macOS those are points,
which is what ``screencapture -R`` takes, and it returns full Retina pixels.
Elsewhere ``QScreen.grabWindow`` does the job in native pixels.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from typing import Callable, Optional, Tuple

from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen, QScreen
from PySide6.QtWidgets import QWidget

BBox = Tuple[int, int, int, int]  # x1, y1, x2, y2 (global logical)


def _screencapture(args) -> Image.Image:
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        subprocess.run(["screencapture", "-x", "-t", "png", *args, path], check=True)
        with Image.open(path) as im:
            return im.convert("RGB")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _qimage_to_pil(img: QImage) -> Image.Image:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    data = bytes(img.constBits())
    return Image.frombuffer("RGB", (w, h), data, "raw", "RGB", img.bytesPerLine(), 1).copy()


def grab_region(bbox: BBox, screen: Optional[QScreen] = None) -> Image.Image:
    x1, y1, x2, y2 = bbox
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    if sys.platform == "darwin":
        return _screencapture(["-R", f"{x1},{y1},{w},{h}"])
    screen = screen or QGuiApplication.screenAt(QPoint(x1, y1)) or QGuiApplication.primaryScreen()
    g = screen.geometry()
    return _qimage_to_pil(screen.grabWindow(0, x1 - g.x(), y1 - g.y(), w, h).toImage())


def grab_screen(screen: Optional[QScreen] = None) -> Image.Image:
    if sys.platform == "darwin":
        return _screencapture([])
    screen = screen or QGuiApplication.primaryScreen()
    return _qimage_to_pil(screen.grabWindow(0).toImage())


class RegionSelector(QWidget):
    """Dim the screen under the cursor, let the user drag a box, call ``on_done(bbox, screen)``.

    ``on_done(None, screen)`` means cancelled (Escape or right-click).
    Keep a reference to the instance while it is showing.
    """

    def __init__(self, on_done: Callable[[Optional[BBox], QScreen], None]) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.on_done = on_done
        self.screen_ = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.start: Optional[QPoint] = None
        self.end: Optional[QPoint] = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(self.screen_.geometry())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _selection(self) -> Optional[QRect]:
        if self.start is None or self.end is None:
            return None
        return QRect(self.start, self.end).normalized()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        sel = self._selection()
        if sel is not None:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(sel, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(255, 255, 255), 2))
            p.drawRect(sel)
        else:
            p.setPen(QPen(QColor(255, 255, 255)))
            f = QFont()
            f.setPointSize(20)
            p.setFont(f)
            p.drawText(self.rect().adjusted(0, 60, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       "Drag over the text you want read.   Esc cancels.")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = self.end = event.position().toPoint()
            self.update()
        else:
            self._finish(None)

    def mouseMoveEvent(self, event) -> None:
        if self.start is not None:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.start is None:
            return
        self.end = event.position().toPoint()
        sel = self._selection()
        if sel is None or sel.width() < 8 or sel.height() < 8:
            self._finish(None)
            return
        tl = self.mapToGlobal(sel.topLeft())
        br = self.mapToGlobal(sel.bottomRight())
        self._finish((tl.x(), tl.y(), br.x(), br.y()))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._finish(None)

    def _finish(self, bbox: Optional[BBox]) -> None:
        self.hide()
        screen = self.screen_
        # give the window server a moment to remove the overlay before the screenshot
        QTimer.singleShot(180, lambda: self.on_done(bbox, screen))
        self.deleteLater()
