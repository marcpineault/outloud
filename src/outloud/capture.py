"""Screen capture: a drag-to-select overlay plus platform screenshot helpers.

Coordinates are in Tk screen units. On macOS those are points; ``screencapture``
takes points too and returns full Retina pixels, which is what OCR wants. On
Windows the app switches on DPI awareness at startup so Tk units are pixels.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tkinter as tk
from typing import Callable, Optional, Tuple

from PIL import Image

BBox = Tuple[int, int, int, int]  # x1, y1, x2, y2


def grab_region(bbox: BBox) -> Image.Image:
    x1, y1, x2, y2 = bbox
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    if sys.platform == "darwin":
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            subprocess.run(["screencapture", "-x", "-t", "png", "-R", f"{x1},{y1},{w},{h}", path], check=True)
            with Image.open(path) as im:
                return im.convert("RGB")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=(x1, y1, x1 + w, y1 + h), all_screens=True).convert("RGB")


def grab_screen() -> Image.Image:
    if sys.platform == "darwin":
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            subprocess.run(["screencapture", "-x", "-t", "png", path], check=True)
            with Image.open(path) as im:
                return im.convert("RGB")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    from PIL import ImageGrab

    return ImageGrab.grab(all_screens=True).convert("RGB")


class RegionSelector:
    """Dim the screen, let the user drag a rectangle, hand the bbox to ``on_done``.

    ``on_done(None)`` means cancelled (Escape or right-click).
    """

    def __init__(self, root: tk.Misc, on_done: Callable[[Optional[BBox]], None]) -> None:
        self.on_done = on_done
        self.start: Optional[Tuple[int, int]] = None
        self.rect = None
        top = tk.Toplevel(root)
        self.top = top
        top.overrideredirect(True)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        top.geometry(f"{sw}x{sh}+0+0")
        top.configure(bg="black")
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            sw // 2, 60, text="Drag over the text you want read.   Esc cancels.",
            fill="white", font=("Helvetica", 20),
        )
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        for seq in ("<Escape>", "<Button-3>", "<Button-2>"):
            top.bind(seq, self._cancel)
            self.canvas.bind(seq, self._cancel)
        top.update_idletasks()
        try:
            top.attributes("-alpha", 0.35)
        except tk.TclError:
            pass
        top.lift()
        top.focus_force()
        self.canvas.focus_set()

    def _press(self, event):
        self.start = (event.x, event.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="white", width=2)

    def _drag(self, event):
        if self.start and self.rect:
            self.canvas.coords(self.rect, self.start[0], self.start[1], event.x, event.y)

    def _release(self, event):
        if not self.start:
            return
        ox, oy = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
        x1, y1 = self.start
        x2, y2 = event.x, event.y
        bbox = (ox + min(x1, x2), oy + min(y1, y2), ox + max(x1, x2), oy + max(y1, y2))
        self._close()
        if bbox[2] - bbox[0] < 8 or bbox[3] - bbox[1] < 8:
            self.on_done(None)
            return
        # give the window server a moment to remove the overlay before the screenshot
        self.top.master.after(180, lambda: self.on_done(bbox))

    def _cancel(self, _event=None):
        self._close()
        self.on_done(None)

    def _close(self):
        try:
            self.top.withdraw()
            self.top.update_idletasks()
            self.top.destroy()
        except tk.TclError:
            pass
