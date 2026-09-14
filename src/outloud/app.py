"""OutLoud main window (Qt / PySide6).

    top bar     Open PDF | ◀ [page] / N ▶ | − + Fit width | Read from screen ▾ | Back to the PDF | Global hotkeys
    centre      the PDF, scrolling like a book, the sentence being read highlighted on the page
                (or a text panel when reading the clipboard / a screen capture)
    bottom bar  ▶ Play  ■ Stop  ⏮ ⏭ sentence | Voice | Speed | status

Click any sentence to hear it from there. Type a page number and press Enter to jump.
The Reader speaks on a worker thread and posts events to a queue polled by a QTimer.
"""
from __future__ import annotations

import os
import queue
import sys
import time
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIntValidator, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QSizePolicy, QSlider, QStackedWidget, QTextEdit, QToolBar, QToolButton, QWidget,
)

from . import __version__, capture, config, ocr, textsplit
from .hotkeys import DEFAULT_COMBOS, Hotkeys, combo_label, copy_selection
from .pdf import PageText, PdfDocument
from .reader import Reader
from .textsplit import Chunk
from .tts import TTSError, Voice, get_backend, pick_default_voice
from .viewer import PdfViewer

APP_NAME = "OutLoud"


class TextPanel(QTextEdit):
    """Read-only text view for clipboard / screen text; click a sentence to read from it."""

    clicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        f = QFont()
        f.setPointSize(16)
        self.setFont(f)
        self.document().setDocumentMargin(28)
        self.setStyleSheet("QTextEdit { background: #fbfbf8; color: #1a1a1a; border: none; }")

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.cursorForPosition(event.position().toPoint()).position())

    def highlight(self, start: int, end: int) -> None:
        sel = QTextEdit.ExtraSelection()
        sel.cursor = QTextCursor(self.document())
        sel.cursor.setPosition(start)
        sel.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(255, 232, 92))
        fmt.setForeground(QColor(17, 17, 17))
        sel.format = fmt
        self.setExtraSelections([sel])
        rect = self.cursorRect(sel.cursor)
        vsb = self.verticalScrollBar()
        vh = self.viewport().height()
        if rect.top() < 10 or rect.bottom() > vh - 10:
            vsb.setValue(vsb.value() + rect.top() - int(vh * 0.3))

    def clear_highlight(self) -> None:
        self.setExtraSelections([])


class MainWindow(QMainWindow):
    def __init__(self, initial_file: Optional[str] = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 840)
        self.setAcceptDrops(True)

        self.cfg = config.load()
        self.events: "queue.Queue" = queue.Queue()
        self.backend = get_backend()
        self.reader = Reader(self.backend, self.events)
        self.reader.voice = self.cfg.get("voice") or None
        self.reader.rate = int(self.cfg.get("rate", 180))

        self.pdf: Optional[PdfDocument] = None
        self.page_maps: Dict[int, PageText] = {}
        self.reading_page: Optional[int] = None  # page whose chunks are loaded in the reader
        self.text_chunks: List[Chunk] = []
        self.hotkeys: Optional[Hotkeys] = None
        self.voices: List[Voice] = []
        self._selector = None

        self._build()
        self._fill_voices()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_events)
        self._timer.start(50)
        if self.cfg.get("hotkeys"):
            QTimer.singleShot(400, lambda: self._toggle_hotkeys(True))
        if initial_file:
            QTimer.singleShot(150, lambda: self.open_file(initial_file))

    # ------------------------------------------------------------------ UI
    def _action(self, text: str, slot, shortcut: Optional[str] = None, tip: Optional[str] = None) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setToolTip(tip + (f"  ({act.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})" if shortcut else ""))
        return act

    def _build(self) -> None:
        self.viewer = PdfViewer()
        self.viewer.clicked.connect(self._pdf_clicked)
        self.viewer.currentPageChanged.connect(self._page_changed)
        self.textpanel = TextPanel()
        self.textpanel.clicked.connect(self._text_clicked)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.viewer)
        self.stack.addWidget(self.textpanel)
        self.setCentralWidget(self.stack)

        top = QToolBar("Document")
        top.setMovable(False)
        top.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, top)

        self.open_act = self._action("Open PDF…", lambda: self.open_file(), "Ctrl+O", "Open a PDF or text file")
        top.addAction(self.open_act)
        top.addSeparator()
        self.prev_page_act = self._action("◀", lambda: self.goto_page(self.viewer.current_page - 1), None, "Previous page")
        top.addAction(self.prev_page_act)
        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(64)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.setPlaceholderText("page")
        self.page_edit.setToolTip("Type a page number and press Enter")
        self.page_edit.returnPressed.connect(self._goto_typed)
        top.addWidget(self.page_edit)
        self.page_total = QLabel(" / 0 ")
        top.addWidget(self.page_total)
        self.next_page_act = self._action("▶", lambda: self.goto_page(self.viewer.current_page + 1), None, "Next page")
        top.addAction(self.next_page_act)
        self.goto_act = self._action("Go to page", lambda: (self.page_edit.setFocus(), self.page_edit.selectAll()), "Ctrl+G")
        self.addAction(self.goto_act)
        top.addSeparator()
        self.zoom_out_act = self._action("−", self.viewer.zoom_out, "Ctrl+-", "Zoom out")
        self.zoom_in_act = self._action("+", self.viewer.zoom_in, "Ctrl+=", "Zoom in")
        self.fit_act = self._action("Fit width", self.viewer.fit_width, "Ctrl+0", "Fit the page to the window")
        for a in (self.zoom_out_act, self.zoom_in_act, self.fit_act):
            top.addAction(a)
        top.addSeparator()

        screen_menu = QMenu(self)
        self.clip_act = self._action("Read clipboard", self.read_clipboard, None, "Read whatever you last copied")
        self.area_act = self._action("Read screen area…", self.read_area, None, "Drag a box over anything on screen")
        self.whole_act = self._action("Read whole screen", self.read_screen, None, "Read everything on the main display")
        for a in (self.clip_act, self.area_act, self.whole_act):
            screen_menu.addAction(a)
        screen_btn = QToolButton()
        screen_btn.setText("Read from screen ▾")
        screen_btn.setMenu(screen_menu)
        screen_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        top.addWidget(screen_btn)
        self.back_act = self._action("Back to the PDF", self._back_to_pdf, None, "Show the PDF again")
        self.back_act.setVisible(False)
        top.addAction(self.back_act)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top.addWidget(spacer)
        self.hotkeys_act = QAction("Global hotkeys", self)
        self.hotkeys_act.setCheckable(True)
        self.hotkeys_act.setChecked(bool(self.cfg.get("hotkeys")))
        self.hotkeys_act.setToolTip("Shortcuts that work from any app:\n" + "\n".join(
            f"{combo_label(c)}: {n.replace('_', ' ')}" for n, c in DEFAULT_COMBOS.items()))
        self.hotkeys_act.toggled.connect(self._toggle_hotkeys)
        top.addAction(self.hotkeys_act)

        bottom = QToolBar("Playback")
        bottom.setMovable(False)
        bottom.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, bottom)
        self.play_act = self._action("▶ Play", self.toggle_play, None, "Play / pause (Space)")
        self.stop_act = self._action("■ Stop", self.stop, None, "Stop (Esc)")
        self.prev_act = self._action("⏮ Sentence", lambda: self.reader.seek(-1), None, "Previous sentence (←)")
        self.next_act = self._action("Sentence ⏭", lambda: self.reader.seek(1), None, "Next sentence (→)")
        for a in (self.play_act, self.stop_act, self.prev_act, self.next_act):
            bottom.addAction(a)
        bottom.addSeparator()
        bottom.addWidget(QLabel(" Voice "))
        self.voice_box = QComboBox()
        self.voice_box.setMinimumWidth(240)
        self.voice_box.currentIndexChanged.connect(self._on_voice)
        bottom.addWidget(self.voice_box)
        bottom.addWidget(QLabel("   Speed "))
        self.rate_slider = QSlider(Qt.Orientation.Horizontal)
        self.rate_slider.setRange(100, 350)
        self.rate_slider.setSingleStep(5)
        self.rate_slider.setPageStep(20)
        self.rate_slider.setFixedWidth(150)
        self.rate_slider.setValue(self.reader.rate)
        self.rate_slider.valueChanged.connect(self._on_rate)
        bottom.addWidget(self.rate_slider)
        self.rate_label = QLabel(f" {self.reader.rate} wpm ")
        self.rate_label.setMinimumWidth(70)
        bottom.addWidget(self.rate_label)
        self.statusBar().setSizeGripEnabled(False)

        # menu bar (on the Mac this is the system menu bar)
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        file_menu.addAction(self.open_act)
        file_menu.addSeparator()
        file_menu.addAction(self.clip_act)
        file_menu.addAction(self.area_act)
        file_menu.addAction(self.whole_act)
        read_menu = mb.addMenu("Read")
        for a in (self.play_act, self.stop_act, self.prev_act, self.next_act):
            read_menu.addAction(a)
        read_menu.addSeparator()
        read_menu.addAction(self.hotkeys_act)
        view_menu = mb.addMenu("View")
        for a in (self.goto_act, self.prev_page_act, self.next_page_act, self.zoom_in_act, self.zoom_out_act, self.fit_act):
            view_menu.addAction(a)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_play)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.stop)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self._seek_key(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self._seek_key(1))
        QShortcut(QKeySequence("Ctrl+V"), self, self.read_clipboard)
        self._set_pdf_controls(False)

    def _fill_voices(self) -> None:
        try:
            voices = self.backend.voices()
        except Exception as exc:
            voices = []
            self._status(f"Could not list voices: {exc}")
        self.voices = sorted(voices, key=lambda v: (not v.lang.lower().startswith("en"), v.lang, v.name))
        if not self.reader.voice:
            self.reader.voice = pick_default_voice(self.voices)
        self.voice_box.blockSignals(True)
        self.voice_box.clear()
        self.voice_box.addItem("System default voice")
        for v in self.voices:
            self.voice_box.addItem(f"{v.name}  ({v.lang})" if v.lang else v.name)
        current = self.reader.voice or ""
        self.voice_box.setCurrentIndex(next((i + 1 for i, v in enumerate(self.voices) if v.id == current), 0))
        self.voice_box.blockSignals(False)

    def _status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    def _set_pdf_controls(self, on: bool) -> None:
        for a in (self.prev_page_act, self.next_page_act, self.zoom_in_act, self.zoom_out_act, self.fit_act, self.goto_act):
            a.setEnabled(on)
        self.page_edit.setEnabled(on)

    # ---------------------------------------------------------------- pages
    def open_file(self, path: Optional[str] = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open a PDF or text file", "", "PDF and text (*.pdf *.txt *.md);;All files (*)")
            if not path:
                return
        if not path.lower().endswith(".pdf"):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{exc}")
                return
            self._show_text(text, os.path.basename(path), autoplay=False)
            return
        try:
            doc = PdfDocument(path)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not open the PDF:\n{exc}")
            return
        self.reader.stop()
        self._close_pdf()
        self.pdf = doc
        self.viewer.set_document(doc)
        self.page_edit.setValidator(QIntValidator(1, doc.page_count, self))
        self.page_total.setText(f" / {doc.page_count} ")
        self.page_edit.setText("1")
        self._set_pdf_controls(True)
        self.stack.setCurrentIndex(0)
        self.back_act.setVisible(False)
        self.setWindowTitle(f"{os.path.basename(path)}  —  {APP_NAME}")
        self._status(f"{doc.page_count} pages. Press Play, or click any sentence to start there.")
        self.viewer.setFocus()

    def _close_pdf(self) -> None:
        if self.pdf is not None:
            self.pdf.close()
        self.pdf = None
        self.page_maps = {}
        self.reading_page = None
        self.viewer.set_document(None)
        self.page_total.setText(" / 0 ")
        self.page_edit.clear()
        self._set_pdf_controls(False)
        self.setWindowTitle(APP_NAME)

    def goto_page(self, index: int) -> None:
        if self.pdf is None:
            return
        index = max(0, min(index, self.pdf.page_count - 1))
        self.viewer.goto_page(index)
        self.page_edit.setText(str(index + 1))

    def _goto_typed(self) -> None:
        try:
            self.goto_page(int(self.page_edit.text()) - 1)
        except ValueError:
            pass
        self.viewer.setFocus()

    def _page_changed(self, index: int) -> None:
        if not self.page_edit.hasFocus():
            self.page_edit.setText(str(index + 1) if self.pdf else "")

    def _page_map(self, index: int) -> Optional[PageText]:
        if self.pdf is None:
            return None
        pt = self.page_maps.get(index)
        if pt is None:
            pt = self.pdf.page_text_map(index)
            if not pt.chunks and self.pdf.looks_scanned(index):
                self._status(f"Page {index + 1} is a scan, reading it with OCR…")
                QApplication.processEvents()
                w, h = self.pdf.page_size(index)
                try:
                    image = self.pdf.render(index, 2.0)
                    lines = ocr.recognize_lines(image)
                    if lines is None:
                        pt = PageText([], w, h, text=textsplit.normalize(ocr.recognize(image)))
                    else:
                        pt = PageText.from_ocr_lines(ocr.layout_lines(lines), w, h)
                except ocr.OCRUnavailable as exc:
                    self._status(str(exc).splitlines()[0])
                except Exception as exc:
                    self._status(f"OCR failed on page {index + 1}: {exc}")
            self.page_maps[index] = pt
            while len(self.page_maps) > 80:
                self.page_maps.pop(next(iter(self.page_maps)))
        return pt

    # ------------------------------------------------------------ transport
    def toggle_play(self) -> None:
        state = self.reader.state
        if state == "playing":
            self.reader.pause()
            return
        if state == "paused":
            self.reader.play()
            return
        if self.stack.currentIndex() == 1:
            if not self.text_chunks:
                self._status("Nothing to read here.")
                return
            self.reader.load(self.text_chunks)
            self.reading_page = None
            self.reader.play(0)
            return
        if self.pdf is None:
            self._status("Open a PDF first, or use Read from screen.")
            return
        page = self.viewer.current_page
        if self.reading_page == page and self.reader.chunks and self.reader.index < len(self.reader.chunks):
            self.reader.play(self.reader.index)  # carry on where it stopped
        else:
            self.start_reading_page(page)

    def start_reading_page(self, index: int, chunk: int = 0) -> None:
        if self.pdf is None:
            return
        while index < self.pdf.page_count:
            pt = self._page_map(index)
            if pt is not None and pt.chunks:
                break
            index += 1
        else:
            self.reading_page = None
            self.viewer.clear_highlight()
            self._status("Nothing more to read.")
            return
        self.reader.load(pt.chunks)
        self.reading_page = index
        self.reader.play(chunk)

    def stop(self) -> None:
        self.reader.stop()
        self.viewer.clear_highlight()
        self.textpanel.clear_highlight()
        self.play_act.setText("▶ Play")
        self._status("Stopped.")

    def _seek_key(self, delta: int) -> None:
        if self.reader.state != "idle":
            self.reader.seek(delta)

    def _pdf_clicked(self, page: int, x: float, y: float) -> None:
        pt = self._page_map(page)
        if pt is None:
            return
        ci = pt.chunk_at_point(x, y)
        if ci is None:
            return
        if self.reading_page != page:
            self.reader.load(pt.chunks)
            self.reading_page = page
        self.reader.play(ci)

    def _text_clicked(self, offset: int) -> None:
        if not self.text_chunks:
            return
        ci = textsplit.chunk_at(self.text_chunks, offset)
        if self.reading_page is not None or not self.reader.chunks:
            self.reader.load(self.text_chunks)
            self.reading_page = None
        self.reader.play(ci)

    def _on_voice(self, index: int) -> None:
        self.reader.voice = None if index <= 0 else self.voices[index - 1].id
        self.cfg["voice"] = self.reader.voice or ""
        config.save(self.cfg)
        if self.reader.state == "playing":
            self.reader.play(self.reader.index)

    def _on_rate(self, value: int) -> None:
        rate = int(round(value / 5.0) * 5)
        self.reader.rate = rate
        self.rate_label.setText(f" {rate} wpm ")
        self.cfg["rate"] = rate
        config.save(self.cfg)

    # -------------------------------------------------------- text sources
    def _show_text(self, text: str, title: str, autoplay: bool = True) -> None:
        text = textsplit.normalize(text)
        if not text.strip():
            self._status(f"No text found in the {title}." if not title.endswith((".txt", ".md")) else "That file is empty.")
            return
        self.reader.stop()
        self.textpanel.setPlainText(text)
        self.textpanel.clear_highlight()
        self.text_chunks = textsplit.split_sentences(text)
        self.stack.setCurrentIndex(1)
        self.back_act.setVisible(self.pdf is not None)
        self.setWindowTitle(f"{title}  —  {APP_NAME}")
        self.reader.load(self.text_chunks)
        self.reading_page = None
        if autoplay:
            self.reader.play(0)
        else:
            self._status("Press Play, or click a sentence to start there.")

    def _back_to_pdf(self) -> None:
        self.reader.stop()
        self.stack.setCurrentIndex(0)
        self.back_act.setVisible(False)
        if self.pdf is not None:
            self.setWindowTitle(f"{os.path.basename(self.pdf.path)}  —  {APP_NAME}")
        self.viewer.setFocus()

    def read_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text.strip():
            self._status("The clipboard has no text.")
            return
        self._show_text(text, "clipboard")

    def read_area(self) -> None:
        self.reader.stop()
        self.hide()

        def done(bbox, screen):
            self.show()
            self.raise_()
            self.activateWindow()
            self._selector = None
            if bbox is None:
                self._status("Capture cancelled.")
                return
            self._ocr_and_show(lambda: capture.grab_region(bbox, screen))

        def start():
            self._selector = capture.RegionSelector(done)

        QTimer.singleShot(200, start)

    def read_screen(self) -> None:
        self.reader.stop()
        self.hide()

        def go():
            try:
                image = capture.grab_screen()
            except Exception as exc:
                self.show()
                QMessageBox.critical(self, APP_NAME, f"Capture failed:\n{exc}")
                return
            self.show()
            self.raise_()
            self._ocr_and_show(lambda: image)

        QTimer.singleShot(350, go)

    def _ocr_and_show(self, get_image) -> None:
        try:
            image = get_image()
            self._status("Reading the text on screen…")
            QApplication.processEvents()
            text = ocr.recognize(image)
        except ocr.OCRUnavailable as exc:
            QMessageBox.critical(self, "OCR not available", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Capture failed:\n{exc}")
            return
        if not text.strip():
            self._status("No text found. If macOS just asked for Screen Recording permission, allow it and try again.")
            return
        self._show_text(text, "screen")

    # -------------------------------------------------------------- hotkeys
    def _toggle_hotkeys(self, on: bool) -> None:
        if on:
            if self.hotkeys is None:
                self.hotkeys = Hotkeys(self._on_hotkey)
            ok, msg = self.hotkeys.start()
            self.hotkeys_act.blockSignals(True)
            self.hotkeys_act.setChecked(ok)
            self.hotkeys_act.blockSignals(False)
            self._status(msg)
        else:
            if self.hotkeys is not None:
                self.hotkeys.stop()
            self._status("Global hotkeys off.")
        self.cfg["hotkeys"] = bool(self.hotkeys_act.isChecked())
        config.save(self.cfg)

    def _on_hotkey(self, name: str) -> None:
        """Listener thread: keyboard work here, UI work via the queue."""
        if name == "read_selection":
            try:
                copy_selection()
            except Exception:
                pass
            time.sleep(0.3)
        self.events.put(("hotkey", name))

    def _hotkey_action(self, name: str) -> None:
        if name == "read_selection":
            self.read_clipboard()
        elif name == "read_area":
            self.read_area()
        elif name == "toggle":
            self.toggle_play()
        elif name == "stop":
            self.stop()

    # --------------------------------------------------------------- events
    def _poll_events(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass

    def _handle(self, ev) -> None:
        kind = ev[0]
        if kind == "chunk":
            i = ev[1]
            self.play_act.setText("⏸ Pause")
            if self.reading_page is not None and self.pdf is not None:
                pt = self.page_maps.get(self.reading_page)
                self.viewer.set_highlight(self.reading_page, pt.rects_for_chunk(i) if pt else [])
                self._status(f"Reading page {self.reading_page + 1} of {self.pdf.page_count}")
            elif i < len(self.text_chunks):
                c = self.text_chunks[i]
                self.textpanel.highlight(c.start, c.end)
                self._status(f"Reading sentence {i + 1} of {len(self.text_chunks)}")
        elif kind == "paused":
            self.play_act.setText("▶ Resume")
            self._status("Paused.")
        elif kind == "resumed":
            self.play_act.setText("⏸ Pause")
        elif kind == "finished":
            self.play_act.setText("▶ Play")
            if self.pdf is not None and self.reading_page is not None and self.stack.currentIndex() == 0 \
                    and self.reading_page + 1 < self.pdf.page_count:
                self.start_reading_page(self.reading_page + 1)
            else:
                self.viewer.clear_highlight()
                self.textpanel.clear_highlight()
                self._status("Finished.")
        elif kind == "stopped":
            self.play_act.setText("▶ Play")
        elif kind == "error":
            self.play_act.setText("▶ Play")
            self.viewer.clear_highlight()
            self._status(f"Speech error: {ev[1]}")
        elif kind == "hotkey":
            self._hotkey_action(ev[1])

    # ------------------------------------------------------------ drag/drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.open_file(path)
                break

    def closeEvent(self, event) -> None:
        self.reader.stop()
        if self.hotkeys is not None:
            self.hotkeys.stop()
        config.save(self.cfg)
        super().closeEvent(event)


class OutLoudApp(QApplication):
    """Handles files opened from Finder / the Dock (macOS QFileOpenEvent)."""

    window: Optional[MainWindow] = None

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.FileOpen and self.window is not None:
            self.window.open_file(e.file())
            return True
        return super().event(e)


# ----------------------------------------------------------------- entry
def _make_app(argv: List[str]) -> OutLoudApp:
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName("OutLoud")
    app = OutLoudApp([sys.argv[0]] + argv)
    app.setStyle("Fusion") if sys.platform not in ("darwin", "win32") else None
    return app


def selftest() -> int:
    """Build the whole window offscreen, list engines, tear down. Used by tests and CI."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = _make_app([])
    win = MainWindow()
    app.window = win
    win.show()
    QTimer.singleShot(300, app.quit)
    app.exec()
    print(f"outloud {__version__}: tts={win.backend.name} voices={len(win.voices)} ocr={ocr.available_backends()} qt=ok")
    return 0


def _sample_pdf(path: str) -> None:
    import pymupdf

    doc = pymupdf.open()
    body = (
        "OutLoud reads this page to you and follows along with a highlighter. Click any sentence "
        "and it starts reading from there. Type a page number at the top and press Enter to jump "
        "straight to it, even in a book with hundreds of pages.\n\n"
        "Scanned pages are read too: when a page has no text layer, the built-in OCR reads the "
        "picture of the page and the highlighter still finds the right line.\n\n"
        "Everything runs on your own computer with the voices already installed. Nothing is uploaded."
    )
    for n in range(1, 4):
        page = doc.new_page()
        page.insert_text((72, 90), f"Chapter {n}", fontsize=22, fontname="helv")
        page.insert_textbox(pymupdf.Rect(72, 120, 540, 700), body + "\n\n" + body, fontsize=12.5, fontname="helv", lineheight=1.45)
        page.insert_text((280, 780), f"{n}", fontsize=10, fontname="helv")
    doc.save(path)
    doc.close()


def screenshot(path: str) -> int:
    """Show the window with a sample PDF and a highlighted sentence, save a PNG, quit."""
    import tempfile

    app = _make_app([])
    win = MainWindow()
    app.window = win
    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    _sample_pdf(pdf_path)
    win.show()
    win.raise_()

    def prepare():
        win.open_file(pdf_path)
        win.viewer.goto_page(0)

    def snap():
        pt = win._page_map(0)
        win.viewer.set_highlight(0, pt.rects_for_chunk(2))
        win.play_act.setText("⏸ Pause")
        win._status("Reading page 1 of 3")
        QTimer.singleShot(400, lambda: (win.grab().save(path), app.quit()))

    QTimer.singleShot(300, prepare)
    QTimer.singleShot(1500, snap)
    app.exec()
    os.unlink(pdf_path)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    if "--screenshot" in argv:
        return screenshot(argv[argv.index("--screenshot") + 1])
    if "--version" in argv:
        print(f"outloud {__version__}")
        return 0
    app = _make_app(argv)
    try:
        win = MainWindow(initial_file=next((a for a in argv if not a.startswith("-") and os.path.exists(a)), None))
    except TTSError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    app.window = win
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
