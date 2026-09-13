"""OutLoud desktop window (Tkinter, ships with Python on Mac and Windows).

Layout
    row 1  Open PDF | Read clipboard | Read screen area | Read whole screen || Play/Pause  Stop  Prev  Next
    row 2  Voice  Speed  [Page nav when a PDF is open]           Global hotkeys [x]
    body   the text, current sentence highlighted; click a sentence then Play to start there,
           or double-click a sentence to jump straight to it
    foot   status line

The Reader speaks on a worker thread and posts events to a queue; Tk polls it.
"""
from __future__ import annotations

import os
import queue
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from . import __version__, capture, config, ocr, textsplit
from .hotkeys import DEFAULT_COMBOS, Hotkeys, combo_label, copy_selection
from .pdf import PdfDocument
from .reader import Reader
from .textsplit import Chunk
from .tts import TTSError, Voice, get_backend, pick_default_voice

APP_NAME = "OutLoud"
MOD = "Command" if sys.platform == "darwin" else "Control"

WELCOME = f"""Welcome to {APP_NAME}.

Open a PDF, paste any text here, or capture text from your screen, then press Play.
Click anywhere in the text and press Play to start from that sentence. Double-click a sentence to jump to it while reading.

Shortcuts inside this window:
  Space = play / pause      Left / Right arrows = previous / next sentence      Escape = stop
  {MOD} + = bigger text      {MOD} - = smaller text

Global hotkeys (tick the box, top right) work from any app:
  {combo_label(DEFAULT_COMBOS['read_selection'])}  reads whatever text you have selected
  {combo_label(DEFAULT_COMBOS['read_area'])}  lets you drag over any part of the screen and reads it
  {combo_label(DEFAULT_COMBOS['toggle'])}  play / pause          {combo_label(DEFAULT_COMBOS['stop'])}  stop
"""


class App:
    def __init__(self, root: tk.Tk, initial_file: Optional[str] = None) -> None:
        self.root = root
        root.title(APP_NAME)
        root.geometry("1080x680")
        root.minsize(640, 400)

        self.cfg = config.load()
        self.events: "queue.Queue" = queue.Queue()
        self.backend = get_backend()
        self.reader = Reader(self.backend, self.events)
        self.reader.voice = self.cfg.get("voice") or None
        self.reader.rate = int(self.cfg.get("rate", 180))

        self.chunks: List[Chunk] = []
        self._chunk_source: Optional[str] = None
        self.pdf: Optional[PdfDocument] = None
        self.page = 0
        self.hotkeys: Optional[Hotkeys] = None
        self.voices: List[Voice] = []

        self._build_ui()
        self._set_text(WELCOME)
        self._poll_events()

        root.protocol("WM_DELETE_WINDOW", self.quit)
        if sys.platform == "darwin":
            root.createcommand("tk::mac::Quit", self.quit)
            root.createcommand("tk::mac::OpenDocument", self._mac_open_documents)
        if self.cfg.get("hotkeys"):
            root.after(300, lambda: self._toggle_hotkeys(True))
        if initial_file:
            root.after(150, lambda: self.open_file(initial_file))

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        r = self.root
        bar = ttk.Frame(r, padding=(8, 8, 8, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="Open PDF…", command=self.open_file).pack(side="left")
        ttk.Button(bar, text="Read clipboard", command=self.read_clipboard).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Read screen area", command=self.read_area).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Read whole screen", command=self.read_screen).pack(side="left", padx=(6, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        self.play_btn = ttk.Button(bar, text="▶ Play", width=9, command=self.toggle_play)
        self.play_btn.pack(side="left")
        ttk.Button(bar, text="■ Stop", width=7, command=self.stop).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="◀ Prev", width=7, command=lambda: self.reader.seek(-1)).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Next ▶", width=7, command=lambda: self.reader.seek(1)).pack(side="left", padx=(6, 0))

        row2 = ttk.Frame(r, padding=(8, 2, 8, 6))
        row2.pack(fill="x")
        ttk.Label(row2, text="Voice").pack(side="left")
        self.voice_var = tk.StringVar()
        self.voice_box = ttk.Combobox(row2, textvariable=self.voice_var, state="readonly", width=30)
        self.voice_box.pack(side="left", padx=(4, 14))
        self.voice_box.bind("<<ComboboxSelected>>", self._on_voice)
        ttk.Label(row2, text="Speed").pack(side="left")
        self.rate_var = tk.IntVar(value=self.reader.rate)
        self.rate_scale = ttk.Scale(row2, from_=100, to=350, variable=self.rate_var, command=self._on_rate, length=170)
        self.rate_scale.pack(side="left", padx=(4, 4))
        self.rate_label = ttk.Label(row2, text=f"{self.reader.rate} wpm", width=8)
        self.rate_label.pack(side="left")

        self.hotkey_var = tk.BooleanVar(value=bool(self.cfg.get("hotkeys")))
        ttk.Checkbutton(
            row2, text="Global hotkeys", variable=self.hotkey_var,
            command=lambda: self._toggle_hotkeys(self.hotkey_var.get()),
        ).pack(side="right")

        self.page_frame = ttk.Frame(row2)
        ttk.Button(self.page_frame, text="◀", width=3, command=lambda: self.goto_page(self.page - 1)).pack(side="left")
        self.page_label = ttk.Label(self.page_frame, text="", width=14, anchor="center")
        self.page_label.pack(side="left")
        ttk.Button(self.page_frame, text="▶", width=3, command=lambda: self.goto_page(self.page + 1)).pack(side="left")

        body = ttk.Frame(r)
        body.pack(fill="both", expand=True, padx=8)
        self.font_size = int(self.cfg.get("font_size", 15))
        self.text = tk.Text(
            body, wrap="word", font=("Helvetica", self.font_size), padx=14, pady=12,
            undo=True, spacing2=3, spacing3=10, relief="flat", highlightthickness=0,
        )
        sb = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("current", background="#ffe97a", foreground="#111111")
        self.text.bind("<Double-Button-1>", self._on_double_click)
        self.text.bind("<space>", self._on_space)
        self.text.bind("<Left>", lambda e: self._transport_key(lambda: self.reader.seek(-1)))
        self.text.bind("<Right>", lambda e: self._transport_key(lambda: self.reader.seek(1)))
        self.text.bind("<Escape>", lambda e: self.stop())
        for seq, delta in ((f"<{MOD}-equal>", 1), (f"<{MOD}-plus>", 1), (f"<{MOD}-minus>", -1)):
            r.bind_all(seq, lambda e, d=delta: self._zoom(d))
        r.bind_all(f"<{MOD}-o>", lambda e: self.open_file())

        self.status = ttk.Label(r, text="", anchor="w", padding=(8, 4))
        self.status.pack(fill="x")
        self._fill_voices()
        self.text.focus_set()

    def _fill_voices(self) -> None:
        try:
            self.voices = self.backend.voices()
        except Exception as exc:
            self.voices = []
            self._status(f"Could not list voices: {exc}")
        english_first = sorted(self.voices, key=lambda v: (not v.lang.lower().startswith("en"), v.lang, v.name))
        self.voices = english_first
        if not self.reader.voice:
            self.reader.voice = pick_default_voice(self.voices)
        labels = ["System default voice (silent on Macs whose system voice is Siri)"] + [f"{v.name}  ({v.lang})" if v.lang else v.name for v in self.voices]
        self.voice_box["values"] = labels
        current = self.reader.voice or ""
        idx = next((i + 1 for i, v in enumerate(self.voices) if v.id == current), 0)
        self.voice_box.current(idx)

    def _status(self, msg: str) -> None:
        self.status.config(text=msg)

    def _show_pdf_controls(self, show: bool) -> None:
        if show:
            self.page_frame.pack(side="right", padx=(0, 16))
        else:
            self.page_frame.pack_forget()

    def _zoom(self, delta: int) -> None:
        self.font_size = max(9, min(40, self.font_size + delta))
        self.text.configure(font=("Helvetica", self.font_size))
        self.cfg["font_size"] = self.font_size
        config.save(self.cfg)

    # ------------------------------------------------------------- text/chunks
    def _set_text(self, text: str) -> None:
        self.reader.stop()
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")
        self.text.edit_reset()
        self._chunk_source = None
        self._highlight(None)

    def _prepare_chunks(self) -> None:
        raw = self.text.get("1.0", "end-1c")
        if raw != self._chunk_source:
            self.chunks = textsplit.split_sentences(raw)
            self._chunk_source = raw
            self.reader.load(self.chunks)

    def _offset(self, index: str) -> int:
        return len(self.text.get("1.0", index))

    def _highlight(self, i: Optional[int]) -> None:
        self.text.tag_remove("current", "1.0", "end")
        if i is None or i >= len(self.chunks):
            return
        c = self.chunks[i]
        self.text.tag_add("current", f"1.0+{c.start}c", f"1.0+{c.end}c")
        self.text.see(f"1.0+{c.start}c")

    # ---------------------------------------------------------------- transport
    def toggle_play(self) -> None:
        state = self.reader.state
        if state == "playing":
            self.reader.pause()
            return
        if state == "paused":
            self.reader.play()
            return
        self._prepare_chunks()
        if not self.chunks:
            self._status("Nothing to read yet. Open a PDF, paste text, or capture the screen.")
            return
        start = textsplit.chunk_at(self.chunks, self._offset("insert"))
        self.reader.play(start)

    def stop(self) -> None:
        self.reader.stop()
        self._highlight(None)
        self.play_btn.config(text="▶ Play")
        self._status("Stopped.")

    def _on_space(self, _event):
        self.toggle_play()
        return "break"

    def _transport_key(self, fn):
        if self.reader.state != "idle":
            fn()
            return "break"
        return None

    def _on_double_click(self, event):
        self._prepare_chunks()
        if not self.chunks:
            return
        i = textsplit.chunk_at(self.chunks, self._offset(f"@{event.x},{event.y}"))
        self.reader.play(i)
        return "break"

    def _on_voice(self, _event=None) -> None:
        i = self.voice_box.current()
        self.reader.voice = None if i <= 0 else self.voices[i - 1].id
        self.cfg["voice"] = self.reader.voice or ""
        config.save(self.cfg)
        if self.reader.state == "playing":  # hear the new voice on the current sentence
            self.reader.play(self.reader.index)

    def _on_rate(self, _value=None) -> None:
        rate = int(round(float(self.rate_var.get()) / 5.0) * 5)
        self.reader.rate = rate
        self.rate_label.config(text=f"{rate} wpm")
        self.cfg["rate"] = rate
        config.save(self.cfg)

    # ---------------------------------------------------------------- sources
    def open_file(self, path: Optional[str] = None) -> None:
        if not path:
            path = filedialog.askopenfilename(
                title="Open a PDF or text file",
                filetypes=[("PDF and text", "*.pdf *.txt *.md"), ("PDF", "*.pdf"), ("All files", "*")],
            )
            if not path:
                return
        if not path.lower().endswith(".pdf"):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"Could not open the file:\n{exc}")
                return
            self._close_pdf()
            self.root.title(f"{APP_NAME}  —  {os.path.basename(path)}")
            self._set_text(textsplit.normalize(text))
            self._status(f"Loaded {os.path.basename(path)}. Press Play.")
            return
        try:
            doc = PdfDocument(path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open the PDF:\n{exc}")
            return
        self._close_pdf()
        self.pdf = doc
        self.root.title(f"{APP_NAME}  —  {os.path.basename(path)}")
        self._show_pdf_controls(True)
        self.goto_page(0)
        self._status(f"{doc.page_count} pages. Press Play; pages turn by themselves.")

    def _mac_open_documents(self, *paths) -> None:
        if paths:
            self.open_file(paths[0])

    def _close_pdf(self) -> None:
        if self.pdf is not None:
            try:
                self.pdf.close()
            except Exception:
                pass
        self.pdf = None
        self.page = 0
        self._show_pdf_controls(False)
        self.root.title(APP_NAME)

    def goto_page(self, index: int, autoplay: bool = False) -> None:
        if self.pdf is None or not (0 <= index < self.pdf.page_count):
            return
        self.page = index
        text = self.pdf.page_text(index)
        if self.pdf.looks_scanned(index):
            self._status(f"Page {index + 1} has no text layer, reading it with OCR…")
            self.root.update_idletasks()
            try:
                text = ocr.recognize(self.pdf.render(index))
            except ocr.OCRUnavailable as exc:
                text = ""
                self._status(str(exc).splitlines()[0])
        self._set_text(textsplit.normalize(text) or "(This page has no readable text.)")
        self.page_label.config(text=f"Page {index + 1} / {self.pdf.page_count}")
        if autoplay:
            self.root.after(250, self.toggle_play)

    def read_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self._status("The clipboard has no text.")
            return
        self._load_and_play(text, "clipboard")

    def _load_and_play(self, text: str, source: str) -> None:
        self._close_pdf()
        text = textsplit.normalize(text)
        if not text.strip():
            self._status(f"No text found in the {source}.")
            if source == "screen":
                self._status(
                    "No text found on screen. If macOS just asked for Screen Recording permission, allow it and try again."
                )
            return
        self._set_text(text)
        self._prepare_chunks()
        self.reader.play(0)

    def read_area(self) -> None:
        self.reader.stop()
        self.root.withdraw()

        def done(bbox):
            try:
                if bbox is None:
                    self._status("Capture cancelled.")
                    return
                image = capture.grab_region(bbox)
                self._status("Reading the text on screen…")
                self.root.update_idletasks()
                text = ocr.recognize(image)
                self._load_and_play(text, "screen")
            except ocr.OCRUnavailable as exc:
                messagebox.showerror("OCR not available", str(exc))
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Capture failed:\n{exc}")
            finally:
                self.root.deiconify()

        self.root.after(200, lambda: capture.RegionSelector(self.root, done))

    def read_screen(self) -> None:
        self.reader.stop()
        self.root.withdraw()

        def go():
            try:
                image = capture.grab_screen()
                self.root.deiconify()
                self._status("Reading the text on screen…")
                self.root.update_idletasks()
                text = ocr.recognize(image)
                self._load_and_play(text, "screen")
            except ocr.OCRUnavailable as exc:
                self.root.deiconify()
                messagebox.showerror("OCR not available", str(exc))
            except Exception as exc:
                self.root.deiconify()
                messagebox.showerror(APP_NAME, f"Capture failed:\n{exc}")

        self.root.after(350, go)

    # ---------------------------------------------------------------- hotkeys
    def _toggle_hotkeys(self, on: bool) -> None:
        if on:
            if self.hotkeys is None:
                self.hotkeys = Hotkeys(self._on_hotkey)
            ok, msg = self.hotkeys.start()
            self.hotkey_var.set(ok)
            self._status(msg)
        else:
            if self.hotkeys is not None:
                self.hotkeys.stop()
            self._status("Global hotkeys off.")
        self.cfg["hotkeys"] = bool(self.hotkey_var.get())
        config.save(self.cfg)

    def _on_hotkey(self, name: str) -> None:
        """Runs on the listener thread: do the keyboard work here, UI work on the Tk thread."""
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

    # ----------------------------------------------------------------- events
    def _poll_events(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(50, self._poll_events)

    def _handle(self, ev) -> None:
        kind = ev[0]
        if kind == "chunk":
            i = ev[1]
            self._highlight(i)
            self.play_btn.config(text="⏸ Pause")
            where = f"page {self.page + 1} of {self.pdf.page_count}, " if self.pdf else ""
            self._status(f"Reading {where}sentence {i + 1} of {len(self.chunks)}.")
        elif kind == "paused":
            self.play_btn.config(text="▶ Resume")
            self._status("Paused.")
        elif kind == "resumed":
            self.play_btn.config(text="⏸ Pause")
        elif kind == "finished":
            self._highlight(None)
            self.play_btn.config(text="▶ Play")
            if self.pdf is not None and self.page + 1 < self.pdf.page_count:
                self.goto_page(self.page + 1, autoplay=True)
            else:
                self._status("Finished.")
        elif kind == "stopped":
            self._highlight(None)
            self.play_btn.config(text="▶ Play")
        elif kind == "error":
            self.play_btn.config(text="▶ Play")
            self._highlight(None)
            self._status(f"Speech error: {ev[1]}")
        elif kind == "hotkey":
            self._hotkey_action(ev[1])

    def quit(self) -> None:
        try:
            self.reader.stop()
            if self.hotkeys is not None:
                self.hotkeys.stop()
            config.save(self.cfg)
        finally:
            self.root.destroy()


# --------------------------------------------------------------------- entry
def _windows_dpi() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _bring_to_front(root: tk.Tk) -> None:
    root.lift()
    try:
        root.attributes("-topmost", True)
        root.after(400, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass


def selftest() -> int:
    """Build the whole UI hidden, list engines, tear down. Used by tests and CI."""
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    root.after(400, app.quit)
    root.mainloop()
    print(f"outloud {__version__}: tts={app.backend.name} voices={len(app.voices)} ocr={ocr.available_backends()}")
    return 0


def screenshot(path: str) -> int:
    """Show the window with sample text and a highlighted sentence, save a PNG, quit."""
    root = tk.Tk()
    app = App(root)
    sample = (
        "Reading out loud, without the fuss.\n\n"
        "Open a PDF and OutLoud reads it page by page, turning the pages for you. "
        "Copy a paragraph from any website or email and press one shortcut to hear it. "
        "Drag a box over anything on your screen, even a picture of text, and it is read back to you.\n\n"
        "Everything runs on your own computer with the voices already installed. Nothing is uploaded."
    )
    app._set_text(sample)
    app._prepare_chunks()
    root.lift()
    root.attributes("-topmost", True)

    def snap():
        app._highlight(2)
        root.update()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        capture.grab_region((x - 1, y - 30, x + w + 1, y + h + 1)).save(path)
        app.quit()

    root.after(900, snap)
    root.mainloop()
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
    _windows_dpi()
    root = tk.Tk()
    try:
        App(root, initial_file=next((a for a in argv if not a.startswith("-")), None))
    except TTSError as exc:
        messagebox.showerror(APP_NAME, str(exc))
        return 1
    _bring_to_front(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
